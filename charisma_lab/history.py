"""Build dated pedigree snapshots from already sourced term and result tables."""
from __future__ import annotations
import csv
from collections import defaultdict
from .importers import read_csv,require
from .util import dt,iso,finite_number


def merged_service_years(intervals,cutoff):
    """Union overlapping elected-service intervals; never count future service."""
    clipped=sorted((a,min(b,cutoff)) for a,b in intervals if a<cutoff and b>a)
    merged=[]
    for a,b in clipped:
        if merged and a<=merged[-1][1]: merged[-1]=(merged[-1][0],max(merged[-1][1],b))
        else: merged.append((a,b))
    return sum((b-a).total_seconds() for a,b in merged)/(86400*365.2425)


def build_pedigree_csv(terms_csv,results_csv,candidate_ids,as_of,output,*,history_complete=False):
    """history_complete must reflect an audited history, not merely successful file loading.

    Terms: candidate_id,start,end,available_at,source_url.
    Results: candidate_id,election_id,election_date,available_at,stage,won,
             actual_margin_pp,expected_margin_pp,baseline_train_end,source_url.
    expected_margin_pp must be a pre-race baseline, NOT a fitted value using that race's result.
    Cross-office service must already be joined to the correct FEC ID through a verified person crosswalk.
    """
    cut=dt(as_of); terms=defaultdict(list); results=defaultdict(dict); sources=defaultdict(set)
    for r in read_csv(terms_csv):
        require(r,['candidate_id','start','available_at','source_url'])
        if dt(r['available_at'])>cut: continue
        start=dt(r['start'],end_of_day=False); end=dt(r['end'],end_of_day=False) if r.get('end') else cut
        if end < start: raise ValueError('Term end precedes start.')
        if start>=cut: continue
        terms[r['candidate_id']].append((start,end)); sources[r['candidate_id']].add(r['source_url'])
    for r in read_csv(results_csv):
        require(r,['candidate_id','election_id','election_date','available_at','stage','won','source_url'])
        if r['stage'] not in {'general','special_general','runoff'}: continue
        if r['won'] not in ('0','1'): raise ValueError('won must be 0 or 1.')
        if dt(r['election_date'])>=cut or dt(r['available_at'])>cut: continue
        if r.get('expected_margin_pp'):
            if not r.get('baseline_train_end') or dt(r['baseline_train_end'])>=dt(r['election_date'],end_of_day=False):
                raise ValueError('Historical outperformance baseline must be trained BEFORE each scored election.')
        key=r['candidate_id']; prev=results[key].get(r['election_id'])
        if prev is None or dt(prev['available_at'])<dt(r['available_at']): results[key][r['election_id']]=r
        sources[key].add(r['source_url'])
    fields=['candidate_id','effective_at','available_at','years_elected','general_wins','general_contests',
            'mean_outperformance_pp','baseline_train_end','history_complete','source_url']
    with open(output,'w',newline='',encoding='utf-8') as f:
        writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader()
        for cid in sorted(set(candidate_ids)):
            past=list(results[cid].values()); residuals=[]; baselines=[]
            for r in past:
                if r.get('actual_margin_pp') and r.get('expected_margin_pp'):
                    residuals.append(finite_number(r['actual_margin_pp'],-100,100)-finite_number(r['expected_margin_pp'],-100,100))
                    baselines.append(iso(r['baseline_train_end']))
            # Missing baselines do not become zero outperformance.
            all_residuals=bool(past) and len(residuals)==len(past)
            writer.writerow({'candidate_id':cid,'effective_at':iso(cut),'available_at':iso(cut),
                'years_elected':merged_service_years(terms[cid],cut),
                'general_wins':sum(int(r['won']) for r in past),'general_contests':len(past),
                'mean_outperformance_pp':sum(residuals)/len(residuals) if all_residuals else '',
                'baseline_train_end':max(baselines) if all_residuals else '',
                'history_complete':int(history_complete),
                'source_url':'; '.join(sorted(sources[cid])) or 'history-audit: explicit verification required'})
    return output
