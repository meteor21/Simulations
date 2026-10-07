"""Agent 3: target-specific portrayal, source strata, longitudinal features and review.

These are media-portrayal measurements, NOT survey estimates of the electorate.
"""
from __future__ import annotations
import json
import math
import re
from collections import defaultdict,Counter
from dataclasses import dataclass,asdict
from datetime import timedelta
from pathlib import Path
from .annotate import target_context,name_pattern
from .agents_store import LABELS
from .store import unpack_body
from .util import dt,iso,now,digest,dumps,normal

ISSUES={
 'economy_jobs':r'\b(econom\w*|inflation|jobs?|unemployment|wages?|recession)\b',
 'energy_prices':r'\b(gas prices?|gasoline|energy prices?|oil prices?|utility bills?)\b',
 'healthcare':r'\b(health\s?care|medicare|medicaid|hospitals?|insurance|prescription)\b',
 'immigration':r'\b(immigra\w*|border|deport\w*|asylum)\b',
 'tax_budget':r'\b(taxes?|taxation|budget|deficit|spending|debt ceiling)\b',
 'ethics':r'\b(ethics|scandal|corruption|indict\w*|investigation|conflict of interest)\b',
 'foreign_defense':r'\b(military|defen[sc]e|war|foreign policy|troops?|veterans?)\b',
 'education':r'\b(education|schools?|teachers?|universities|tuition)\b',
 'abortion':r'\b(abortion|reproductive rights|reproductive freedom)\b',
 'crime_safety':r'\b(crime|police|public safety|gun violence)\b',
 'legislation':r'\b(bill|legislation|committee|amendment|roll.call)\b',
 'constituent_service':r'\b(constituent|casework|district office|town hall|local grant)\b',
}

@dataclass(frozen=True)
class FeatureConfig:
    half_life_days:float=90.
    lookback_days:int=731
    mode:str='strict'  # or explicitly retrospective, not a point-in-time backtest
    reviewed_only:bool=True
    model_id:str|None=None
    bias_provider:str|None='AllSides'
    min_outlets:int=2
    min_unique_articles:int=3
    min_recent_articles:int=1
    require_both_scopes:bool=True
    local_weight:float=.5
    def __post_init__(self):
        if self.half_life_days<=0 or self.lookback_days<1: raise ValueError('Positive time parameters required')
        if self.mode not in {'strict','retrospective'}: raise ValueError('Invalid mode')
        if not 0<=self.local_weight<=1: raise ValueError('local_weight must be in [0,1]')
        if self.min_outlets<1 or self.min_unique_articles<1: raise ValueError('Positive coverage minima required')
        if self.min_recent_articles<0: raise ValueError('min_recent_articles must be nonnegative')


def _service_terms(store,cid,cut,mode):
    rows=store.rows('''SELECT t.*,l.observed_at AS link_observed FROM sa_service_terms t
      JOIN sa_identity_links l USING(person_id) WHERE l.candidate_id=?''',(cid,))
    if mode=='strict': rows=[r for r in rows if r['available_at']<=cut and r['link_observed']<=cut]
    return rows


def _during(terms,timestamp):
    if not terms: return None
    return any(t['start_date']<=timestamp and (not t['end_date'] or timestamp<t['end_date']) for t in terms)


def eligible_portrayals(store,cid,as_of,config:FeatureConfig):
    cut=iso(as_of); lower=dt(as_of)-timedelta(days=config.lookback_days)
    if config.mode=='strict':
        identity=store.rows('SELECT known_at FROM cs_candidates WHERE candidate_id=?',(cid,))
        if not identity or dt(identity[0]['known_at'])>dt(cut):
            return [],{'candidate_identity_not_known_by_cutoff':1},[]
    sql='''SELECT v.*,a.url,a.outlet,n.candidate_id,n.model_id,n.sentiment,n.confidence,
        n.entity_status,n.reviewed,n.evidence,n.diagnostics_json,n.annotated_at
        FROM cs_annotations n JOIN cs_versions v USING(version_id) JOIN cs_articles a USING(article_id)
        WHERE n.candidate_id=? AND v.published_at IS NOT NULL AND v.published_at<=?
        AND v.published_at>=? AND n.entity_status IN ('verified','exact_name_context')'''
    params=[cid,cut,lower.isoformat(timespec='seconds')]
    if config.reviewed_only: sql+=' AND n.reviewed=1'
    if config.model_id: sql+=' AND n.model_id=?'; params.append(config.model_id)
    if config.mode=='strict':
        sql+=' AND v.available_at<=? AND n.annotated_at<=?'
        params.extend([cut,cut])
    sql+=' ORDER BY v.available_at DESC,n.reviewed DESC,n.annotated_at DESC,v.version_id'
    rows=store.rows(sql,params)
    selected={}
    for r in rows: selected.setdefault(r['article_id'],r) # one annotated eligible version/model per URL
    terms=_service_terms(store,cid,cut,config.mode)
    result=[]; dropped=Counter()
    for r in selected.values():
        r=dict(r); pub=r['published_at']
        profile=store.profile_for(r['url'],pub,cut,mode=config.mode)
        if not profile: dropped['source_scope_unknown']+=1; continue
        if profile['source_kind'] in {'official','campaign','social','unknown'}:
            dropped['separate_nonnews_channel']+=1; continue
        metadata=json.loads(r['metadata_json']); genre=metadata.get('genre','unknown')
        # A news-only source rating is not an opinion rating. Unknown genre is flagged.
        if genre=='opinion' or profile['source_kind']=='opinion': rating_genre='opinion'
        else: rating_genre='online_news'
        rating=store.rating_for(profile['domain'],pub,cut if config.mode=='strict' else now(),provider=config.bias_provider,genre=rating_genre)
        r.update(scope=profile['scope'],states=json.loads(profile['states_json']),
                 network_group=profile['network_group'],source_kind=profile['source_kind'],
                 historical_scope_verified=profile['historical_scope_verified'],
                 bias_label=rating['label'],bias_index=rating['ordinal_index'],bias_assessments=rating['assessments'],
                 genre=genre,genre_inferred_for_source_rating=genre=='unknown',
                 age_days=(dt(as_of)-dt(pub)).total_seconds()/86400,
                 during_service=_during(terms,pub),body_available=bool(r['body_z']),
                 text_basis='body_excerpt' if r['body_z'] else 'headline_only',
                 retrospective_version=r['available_at']>cut,
                 retrospective_annotation=r['annotated_at']>cut,
                 issue_tags=[k for k,p in ISSUES.items() if re.search(p,r['evidence'],re.I)])
        result.append(r)
    return result,dict(dropped),terms


def summarize(rows,config:FeatureConfig):
    """Equal weight per observed outlet, not per article or ideology.

    Distinct identical texts within an outlet are counted once. Across-outlet
    syndication is shown through an additional deduplicated-content diagnostic.
    Model confidence is deliberately NOT an importance/accuracy weight.
    """
    groups=defaultdict(dict)
    for r in rows:
        key=r['content_hash']
        old=groups[r['outlet']].get(key)
        if old is None or r['published_at']<old['published_at']: groups[r['outlet']][key]=r
    outlet_means=[]; weights=[]; content=defaultdict(list)
    for outlet,items in groups.items():
        records=list(items.values())
        w=[2**(-r['age_days']/config.half_life_days) for r in records]
        mean=sum(x*r['sentiment'] for x,r in zip(w,records))/sum(w)
        outlet_means.append(mean); weights.extend(w)
        for r in records: content[r['content_hash']].append(r)
    score=50*(1+sum(outlet_means)/len(outlet_means)) if outlet_means else None
    unique_rows=[min(v,key=lambda r:r['published_at']) for v in content.values()]
    dedup_w=[2**(-r['age_days']/config.half_life_days) for r in unique_rows]
    dedup=50*(1+sum(w*r['sentiment'] for w,r in zip(dedup_w,unique_rows))/sum(dedup_w)) if dedup_w else None
    sufficient=len(groups)>=config.min_outlets and len(content)>=config.min_unique_articles
    return {'score':score if sufficient else None,'descriptive_score':score,
      'coverage_sufficient':sufficient,'article_urls':len(rows),'outlets':len(groups),
      'unique_text_clusters':len(content),'syndicated_or_identical_url_excess':max(0,len(rows)-len(content)),
      'deduplicated_content_score':dedup,
      'recency_effective_n':sum(weights)**2/sum(w*w for w in weights) if weights else 0.,
      'headline_only_fraction':sum(not r['body_available'] for r in rows)/len(rows) if rows else None,
      'unrated_source_fraction':sum(r['bias_label']=='Unknown' for r in rows)/len(rows) if rows else None,
      'newest_article_age_days':min((r['age_days'] for r in rows),default=None),
      'retrospectively_retrieved_articles':sum(r['retrospective_version'] for r in rows),
      'retrospectively_annotated_articles':sum(r['retrospective_annotation'] for r in rows),
      'historical_scope_unverified_articles':sum(not r['historical_scope_verified'] for r in rows)}


def snapshot(store,cid,as_of,*,cycle=None,state=None,config=None):
    config=config or FeatureConfig(); cut=iso(as_of)
    candidates=store.rows('SELECT * FROM cs_candidates WHERE candidate_id=?',(cid,))
    if not candidates: raise ValueError('Unknown candidate ID')
    candidate=candidates[0]
    if state is None and cycle is not None:
        cycle_rows=store.rows('SELECT state,known_at FROM cs_candidate_cycles WHERE candidate_id=? AND cycle=?',(cid,cycle))
        states={r['state'] for r in cycle_rows if config.mode!='strict' or dt(r['known_at'])<=dt(cut)}
        if len(states)==1: state=next(iter(states))
        elif len(states)>1: raise ValueError('Multiple candidate states in cycle; pass state explicitly')
    rows,dropped,terms=eligible_portrayals(store,cid,cut,config)
    if state is None:
        active_states={t['state'] for t in terms if t['start_date']<=cut and (not t['end_date'] or cut<t['end_date'])}
        if len(active_states)==1:
            state=next(iter(active_states))  # Infer only from a documented office active at this cutoff.
    national=[r for r in rows if r['scope']=='national']
    local=[r for r in rows if r['scope'] in {'state','metro','local'} and state in r['states']] if state else []
    by_scope={scope:summarize([r for r in rows if r['scope']==scope and (scope=='national' or state in r['states'])],config)
              for scope in ['national','state','metro','local']}
    n,l=summarize(national,config),summarize(local,config)
    flags=['media_portrayal_not_representative_public_opinion']
    if config.mode=='retrospective': flags.append('retrospective_reconstruction_not_point_in_time_forecast')
    if not config.reviewed_only: flags.append('contains_unvalidated_automatic_annotations')
    if not state: flags.append('state_not_resolved_local_features_missing')
    if config.mode=='strict' and candidate['known_at']>cut:
        flags.append('candidate_identity_not_known_by_cutoff')
    media=None
    if l['score'] is not None and n['score'] is not None:
        media=config.local_weight*l['score']+(1-config.local_weight)*n['score']
    elif not config.require_both_scopes:
        available=[v['score'] for v in [l,n] if v['score'] is not None]
        media=sum(available)/len(available) if available else None
        flags.append('scope_weight_renormalization_explicitly_enabled')
    else: flags.append('local_or_national_component_missing')
    relevant=national+local
    recent30=summarize([r for r in relevant if r['age_days']<=30],config)
    previous30=summarize([r for r in relevant if 30<r['age_days']<=60],config)
    momentum=None if recent30['score'] is None or previous30['score'] is None else recent30['score']-previous30['score']
    if any(r['retrospective_version'] for r in relevant): flags.append('later_retrieved_versions_present')
    if any(r['retrospective_annotation'] for r in relevant): flags.append('later_annotations_present')
    if any(not r['historical_scope_verified'] for r in relevant): flags.append('current_scope_used_for_historical_articles')
    if not terms: flags.append('service_history_unknown')
    if config.mode=='strict' and candidate['known_at']>cut: media=None
    # Republishing the same exact text cannot make stale coverage recent or
    # manufacture independent observations. Use its earliest observed publication.
    content_ages={}
    for r in relevant:
        content_ages[r['content_hash']]=max(content_ages.get(r['content_hash'],0),r['age_days'])
    if sum(age<=90 for age in content_ages.values())<config.min_recent_articles:
        flags.append('recent_coverage_stale'); media=None
    groups={label:summarize([r for r in relevant if r['bias_label']==label],config)
            for label in [*LABELS,'Unknown','Mixed/Disputed']}
    issues={k:summarize([r for r in relevant if k in r['issue_tags']],config) for k in ISSUES}
    result={'candidate_id':cid,'name':candidate['name'],'cycle':cycle,'state':state,'as_of':cut,
      'mode':config.mode,'reviewed_only':config.reviewed_only,'media_recency_score':media,'national':n,'subnational':l,'scope_detail':by_scope,
      'local_minus_national':l['score']-n['score'] if l['score'] is not None and n['score'] is not None else None,
      'windows':{str(days):summarize([r for r in relevant if r['age_days']<=days],config) for days in [30,90,180,731]},
      'momentum_30d_vs_previous30d':momentum,'source_ideology_strata':groups,'issue_portrayal_proxies':issues,
      'in_office_at_cutoff':_during(terms,cut),
      'during_service':summarize([r for r in relevant if r['during_service'] is True],config),
      'outside_recorded_service':summarize([r for r in relevant if r['during_service'] is False],config),
      'dropped':dropped,'flags':flags,
      'causal_claim':'None: these are descriptive/predictive candidate-portrayal features, not attribution of electoral impact.'}
    config_json=dumps(asdict(config)); sid=digest([cid,cycle,state,cut,config_json])
    store.con.execute('INSERT OR REPLACE INTO sa_snapshots VALUES(?,?,?,?,?,?,?,?)',
       (sid,cid,cycle,cut,config.mode,config_json,dumps(result),now()))
    store.con.commit(); return result


class AnalysisAgent:
    name='AnalysisAgent'
    def __init__(self,store): self.store=store

    def annotate(self,annotator,*,max_pairs=100):
        rows=self.store.rows('''SELECT v.*,c.candidate_id,c.aliases_json,c.name,c.person_id FROM cs_versions v
            JOIN cs_article_candidates ac USING(article_id) JOIN cs_candidates c USING(candidate_id)
            WHERE NOT EXISTS(SELECT 1 FROM cs_annotations n WHERE n.version_id=v.version_id
              AND n.candidate_id=c.candidate_id AND n.model_id=?)
            ORDER BY v.retrieved_at,v.version_id,c.candidate_id LIMIT ?''',(annotator.model_id,max_pairs))
        identities={r['candidate_id']:r['person_id'] for r in self.store.rows('SELECT * FROM sa_identity_links')}
        alias_people=defaultdict(set)
        for c in self.store.rows('SELECT * FROM cs_candidates'):
            for a in json.loads(c['aliases_json']): alias_people[normal(a)].add(identities.get(c['candidate_id'],c['person_id'] or c['candidate_id']))
        counts=Counter()
        for row in rows:
            text=row['title']+'\n'+unpack_body(row); aliases=json.loads(row['aliases_json'])
            contexts,evidence=target_context(text,aliases)
            if not contexts:
                self.store.annotation(row['version_id'],row['candidate_id'],0,model_id=annotator.model_id,
                    confidence=0,entity_status='no_match',reviewed=False,evidence=row['title'] or '[No target]',
                    diagnostics={'reason':'No verified full-name alias in fetched text'})
                counts['no_name_match']+=1; continue
            matched=[a for a in aliases if re.search(name_pattern(a),text,re.I)]
            unique=any(len(alias_people[normal(a)])==1 for a in matched)
            political=bool(re.search(r'\b(senat\w*|congress\w*|presiden\w*|representative|candidate|campaign|election|governor|legislatur\w*)\b',text,re.I))
            entity='exact_name_context' if unique and political else 'needs_review'
            pred=annotator.predict(contexts)
            self.store.annotation(row['version_id'],row['candidate_id'],pred['sentiment'],model_id=annotator.model_id,
              confidence=pred['confidence'],entity_status=entity,reviewed=False,evidence=evidence,
              diagnostics={'probabilities':pred['probabilities'],'text_basis':'body_excerpt' if row['body_z'] else 'headline_only',
                'quote_or_attribution_flag':bool(re.search(r'[“”"]|\b(accused|alleged|claimed|according to)\b',evidence,re.I)),
                'issue_tags':[k for k,p in ISSUES.items() if re.search(p,evidence,re.I)],
                'model_validated_on_elections':False,'warning':'Target portrayal, not inferred voter opinion or outlet endorsement'})
            counts['annotated']+=1
            if entity=='needs_review': counts['needs_review']+=1
        self.store.con.commit(); self.store.event(self.name,'annotate',**dict(counts)); return dict(counts)

    def features(self,cohort,as_of,config=None):
        result=[snapshot(self.store,r['candidate_id'],as_of,cycle=r.get('cycle'),state=r.get('state'),config=config) for r in cohort]
        self.store.event(self.name,'snapshots',rows=len(result),as_of=iso(as_of)); return result

    def monthly_history(self,candidate_id,start='1990-01-01',end=None,*,state=None,cycle=None,config=None,max_months=500):
        end=end or now(); a=dt(start,end_of_day=False); b=dt(end); cutoffs=[]
        while a<b:
            nextmonth=a.replace(year=a.year+(a.month==12),month=a.month%12+1,day=1,hour=0,minute=0,second=0)
            cutoff=min(b,nextmonth-timedelta(seconds=1)); cutoffs.append(cutoff.isoformat()); a=nextmonth
            if len(cutoffs)>max_months: raise ValueError('max_months exceeded')
        return [snapshot(self.store,candidate_id,t,cycle=cycle,state=state,config=config) for t in cutoffs]

    def review_queue(self,limit=200):
        return self.store.rows('''SELECT n.version_id,n.candidate_id,c.name,a.url,a.outlet,v.published_at,
          n.model_id,n.sentiment,n.confidence,n.entity_status,n.evidence,n.diagnostics_json
          FROM cs_annotations n JOIN cs_versions v USING(version_id) JOIN cs_articles a USING(article_id)
          JOIN cs_candidates c USING(candidate_id) WHERE n.reviewed=0
          ORDER BY CASE WHEN n.entity_status='needs_review' THEN 0 ELSE 1 END,n.annotated_at LIMIT ?''',(limit,))


def combine_standing(store,media_features,*,geography,population,election_id='research',weights=(1/3,1/3,1/3)):
    """Bridge to the existing favorability/pedigree tables, never fabricate missing data."""
    from .scoring import favorability,pedigree,ScoreConfig
    if len(weights)!=3 or min(weights)<0 or not math.isclose(sum(weights),1):
        raise ValueError('Three nonnegative weights must sum to one')
    cid=media_features['candidate_id'];cut=dt(media_features['as_of'])
    mode='strict' if media_features.get('mode','strict')=='strict' else 'research'
    f=favorability(store,cid,cut,geography,population,ScoreConfig(),mode=mode)
    p=pedigree(store,cid,cut,mode=mode); r=media_features['media_recency_score']
    values=[f['score'],r,p['score']]
    flags=list(media_features['flags'])+p.get('flags',[])
    flags += [k+'_missing' for k,v in zip(['favorability','recency','pedigree'],values) if v is None]
    score=sum(w*v for w,v in zip(weights,values)) if all(v is not None for v in values) else None
    if election_id!='research':
        roster_ok=store.rows('SELECT * FROM cs_roster WHERE candidate_id=? AND election_id=? AND known_at<=?',
                           (cid,election_id,iso(cut)))
        if not roster_ok: flags.append('contest_membership_not_verified_asof');score=None
    return {'candidate_id':cid,'as_of':iso(cut),'election_id':election_id,'geography':geography,'population':population,
            'favorability_score':f['score'],'media_recency_score':r,'pedigree_score':p['score'],
            'charisma_score':score,'weights':list(weights),'flags':sorted(set(flags)),
            'forecast_ready':False,'interpretation':'Provisional standing index, not a win probability or causal effect.'}
