from __future__ import annotations
import json
import math
from collections import defaultdict
from dataclasses import asdict,dataclass
from datetime import timedelta
import numpy as np
from .store import unpack_body
from .util import digest,dt,dumps,iso,now

@dataclass(frozen=True)
class ScoreConfig:
    news_window_days:int=730
    news_half_life_days:float=90
    survey_window_days:int=365
    survey_half_life_days:float=60
    min_news_articles:int=5
    min_news_outlets:int=3
    min_confidence:float=.60
    require_reviewed:bool=False
    outlet_domains:tuple[str,...]=()
    weights:tuple[float,float,float]=(1/3,1/3,1/3)
    version:str='standing-v0.1-provisional'
    def __post_init__(self):
        if min(self.news_window_days,self.survey_window_days,self.news_half_life_days,self.survey_half_life_days)<=0:
            raise ValueError('Windows and half-lives must be positive.')
        if self.min_news_articles<1 or self.min_news_outlets<1: raise ValueError('Minimum evidence thresholds must be positive.')
        if len(self.weights)!=3 or min(self.weights)<0 or not math.isclose(sum(self.weights),1):
            raise ValueError('Provide three nonnegative weights summing to one.')
        if not 0<=self.min_confidence<=1: raise ValueError('min_confidence must be in [0,1].')


def decay(age_days,half_life):
    if half_life<=0 or age_days<0: raise ValueError('Require nonnegative age and positive half-life.')
    return 2**(-age_days/half_life)


def _identity_known(store,cid,cut):
    rows=store.rows('SELECT known_at FROM cs_candidates WHERE candidate_id=?',(cid,))
    return bool(rows) and dt(rows[0]['known_at'])<=cut


def favorability(store,cid,cut,geo,pop,cfg,mode='strict'):
    rows=store.rows("""SELECT * FROM cs_surveys WHERE candidate_id=? AND geography=? AND population=?
      AND metric='favorability' AND field_end<=? AND available_at<=? ORDER BY available_at""",(cid,geo,pop,iso(cut),iso(cut)))
    if mode=='strict' and not _identity_known(store,cid,cut): rows=[]
    # Deduplicate revisions / syndicated polling releases of the same pollster wave and population.
    waves={}
    for r in rows:
        if (cut-dt(r['field_end'])).total_seconds()/86400<=cfg.survey_window_days:
            waves[(r['pollster'],r['wave_id'])]=r
    by_source=defaultdict(list)
    for r in waves.values():
        age=(cut-dt(r['field_end'])).total_seconds()/86400
        w=decay(age,cfg.survey_half_life_days)*math.sqrt(min(r['sample_size'],2000)/1000)
        by_source[r['pollster']].append((r,w))
    source_scores=[]; source_dk=[]
    for group in by_source.values():
        w=sum(x[1] for x in group)
        source_scores.append(sum((50+50*(r['favorable']-r['unfavorable']))*a for r,a in group)/w)
        known=[(r['dont_know'],a) for r,a in group if r['dont_know'] is not None]
        if known: source_dk.append(sum(v*a for v,a in known)/sum(a for _,a in known))
    return {'score':float(np.mean(source_scores)) if source_scores else None,'waves':len(waves),
            'pollsters':len(source_scores),'dont_know':float(np.mean(source_dk)) if source_dk else None,
            'pollster_dispersion':float(np.std(source_scores,ddof=1)) if len(source_scores)>1 else None,
            'observation_ids':[r['observation_id'] for r in waves.values()],
            'note':'Net favorability mapped to 0-100, not win probability. Approval is NOT substituted.'}


def news(store,cid,cut,cfg,mode):
    raw=store.rows("""SELECT v.version_id,v.article_id,v.published_at,v.indexed_at,v.available_at,
       v.content_hash,(v.body_z IS NOT NULL) AS has_body,a.url,a.outlet,n.sentiment,n.confidence,n.entity_status,
       n.reviewed,n.model_id,n.diagnostics_json,n.annotated_at
       FROM cs_annotations n JOIN cs_versions v USING(version_id)
       JOIN cs_articles a USING(article_id) WHERE n.candidate_id=?""",(cid,))
    eligible=[]; exclusion=defaultdict(int)
    if mode=='strict' and not _identity_known(store,cid,cut):
        exclusion['candidate_identity_not_known_by_cutoff']=len(raw)
        raw=[]
    for r in raw:
        if cfg.outlet_domains and r['outlet'] not in cfg.outlet_domains:
            exclusion['outside_panel']+=1; continue
        if r['entity_status'] not in {'verified','exact_name_context'}:
            exclusion['unresolved_identity']+=1; continue
        if cfg.require_reviewed and not r['reviewed']:
            exclusion['unreviewed']+=1; continue
        if r['confidence']<cfg.min_confidence:
            exclusion['low_model_confidence']+=1; continue
        if mode=='strict' and dt(r['available_at'])>cut:
            exclusion['version_not_available_by_cutoff']+=1; continue
        if mode=='strict' and dt(r['annotated_at'])>cut:
            exclusion['annotation_not_available_by_cutoff']+=1; continue
        when=r['published_at']
        if when is None:
            if mode=='strict':
                exclusion['publication_date_unknown']+=1; continue
            when=r['indexed_at']
        if not when:
            exclusion['no_article_date']+=1; continue
        age=(cut-dt(when)).total_seconds()/86400
        if age<0 or age>cfg.news_window_days:
            exclusion['outside_time_window']+=1; continue
        r['age']=age; r['date_used']=when; eligible.append(r)
    # One eligible version and annotation per URL; favor reviewed evidence, then latest version.
    eligible.sort(key=lambda r:(r['reviewed'],r['available_at'],bool(r['has_body']),r['annotated_at']))
    latest={r['article_id']:r for r in eligible}
    # Global exact-content deduplication; not a claim of complete near-duplicate/wire attribution.
    unique={}
    for r in sorted(latest.values(),key=lambda r:(r['date_used'],r['url'])):
        unique.setdefault(r['content_hash'],r)
    by_outlet=defaultdict(list)
    for r in unique.values(): by_outlet[r['outlet']].append(r)
    def outlet_balanced(half_life):
        means={}
        for outlet,group in by_outlet.items():
            weights=[decay(r['age'],half_life) for r in group]
            means[outlet]=50+50*sum(w*r['sentiment'] for w,r in zip(weights,group))/sum(weights)
        return (float(np.mean(list(means.values()))) if means else None),means
    raw_score,outlet_scores=outlet_balanced(cfg.news_half_life_days)
    enough=len(unique)>=cfg.min_news_articles and len(by_outlet)>=cfg.min_news_outlets
    s30,_=outlet_balanced(30); s180,_=outlet_balanced(180)
    body_count=sum(bool(r['has_body']) for r in unique.values())
    flags=[]
    if len(unique)<cfg.min_news_articles: flags.append('insufficient_news_articles')
    if len(by_outlet)<cfg.min_news_outlets: flags.append('insufficient_outlet_coverage')
    if not cfg.outlet_domains: flags.append('outlet_panel_not_fixed')
    if any(not r['reviewed'] for r in unique.values()): flags.append('unvalidated_automatic_annotations')
    if any(dt(r['available_at'])>cut for r in unique.values()): flags.append('historical_content_version_unverified')
    if any(dt(r['annotated_at'])>cut for r in unique.values()): flags.append('later_annotations_present')
    if any(not r['published_at'] for r in unique.values()): flags.append('index_date_used_as_publication_proxy')
    if body_count<len(unique): flags.append('headline_only_evidence_present')
    return {'score':raw_score if enough else None,'raw_diagnostic_score':raw_score,
            'momentum_30_minus_180':s30-s180 if s30 is not None else None,
            'unique_articles':len(unique),'outlets':len(by_outlet),'body_articles':body_count,
            'exact_duplicate_copies_removed':len(latest)-len(unique),'outlet_scores':outlet_scores,
            'configured_outlets':len(cfg.outlet_domains),
            'missing_panel_outlets':sorted(set(cfg.outlet_domains)-set(by_outlet)),
            'latest_article_age_days':min((r['age'] for r in unique.values()),default=None),
            'outlet_dispersion':float(np.std(list(outlet_scores.values()),ddof=1)) if len(outlet_scores)>1 else None,
            'version_ids':[r['version_id'] for r in unique.values()],
            'model_ids':sorted({r['model_id'] for r in unique.values()}),
            'flags':flags,'exclusions':dict(exclusion)}


def pedigree(store,cid,cut,mode='strict'):
    if mode=='strict' and not _identity_known(store,cid,cut):
        return {'score':None,'flags':['candidate_registry_not_verified_asof']}
    rows=store.rows('''SELECT * FROM cs_pedigree WHERE candidate_id=? AND effective_at<=?
      AND available_at<=? ORDER BY effective_at DESC,available_at DESC LIMIT 1''',(cid,iso(cut),iso(cut)))
    if not rows: return {'score':None,'flags':['no_asof_pedigree_record']}
    r=rows[0]
    if not r['history_complete']: return {'score':None,'flags':['pedigree_history_incomplete'],'observation_id':r['observation_id']}
    years=r['years_elected']; wins=r['general_wins']; contests=r['general_contests']; op=r['mean_outperformance_pp']
    experience=100*(1-math.exp(-years/8))
    electoral_record=100*(1-math.exp(-wins/3))
    flags=['pedigree_transform_provisional']
    if contests==0:
        # This is a visible modeling prior ONLY for an explicitly verified no-prior-contest record.
        relative=50.; flags.append('verified_newcomer_neutral_outperformance_prior')
    elif op is None:
        return {'score':None,'experience_score':experience,'record_score':electoral_record,
                'flags':['historical_outperformance_missing'],'observation_id':r['observation_id']}
    else:
        relative=50+50*math.tanh(op/10)
    return {'score':(experience+electoral_record+relative)/3,'experience_score':experience,
            'record_score':electoral_record,'outperformance_score':relative,'years_elected':years,
            'general_wins':wins,'general_contests':contests,'mean_outperformance_pp':op,
            'observation_id':r['observation_id'],'flags':flags}


def score_candidate(store,candidate_id,as_of,*,geography,population,election_id='research',mode='strict',config=None):
    if mode not in {'strict','research'}: raise ValueError('mode must be strict or research')
    cfg=config or ScoreConfig(); cut=dt(as_of)
    candidate=store.rows('SELECT * FROM cs_candidates WHERE candidate_id=?',(candidate_id,))
    if not candidate: raise ValueError('Unknown candidate ID')
    f=favorability(store,candidate_id,cut,geography,population,cfg,mode=mode)
    r=news(store,candidate_id,cut,cfg,mode); p=pedigree(store,candidate_id,cut,mode=mode)
    values=[f['score'],r['score'],p['score']]
    flags=['provisional_index_not_validated_win_probability']+r['flags']+p['flags']
    flags += [name+'_missing' for name,v in zip(['favorability','recency','pedigree'],values) if v is None]
    identity_ok=dt(candidate[0]['known_at'])<=cut
    if not identity_ok: flags.append('candidate_registry_not_verified_asof')
    roster_ok=True
    if election_id!='research':
        roster_ok=bool(store.rows('SELECT * FROM cs_roster WHERE candidate_id=? AND election_id=? AND known_at<=?',
                                  (candidate_id,election_id,iso(cut))))
        if not roster_ok: flags.append('contest_membership_not_verified_asof')
    composite=sum(w*v for w,v in zip(cfg.weights,values)) if all(v is not None for v in values) else None
    if mode=='strict' and not (identity_ok and roster_ok): composite=None
    result={'candidate_id':candidate_id,'election_id':election_id,'as_of':iso(cut),'mode':mode,
            'geography':geography,'population':population,'favorability_score':f['score'],
            'recency_score':r['score'],'pedigree_score':p['score'],'charisma_score':composite,
            'forecast_ready':False,'flags':sorted(set(flags)),'favorability':f,'recency':r,'pedigree':p}
    config_json=dumps(asdict(cfg))
    snapshot_id=digest([candidate_id,election_id,iso(cut),mode,geography,population,config_json])
    store.con.execute('INSERT OR REPLACE INTO cs_scores VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
        (snapshot_id,candidate_id,election_id,iso(cut),mode,geography,population,*values,composite,
         dumps(result['flags']),dumps(result),config_json,now()))
    store.con.commit()
    return result
