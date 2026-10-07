"""Illustrative capacity arithmetic, not a forecast of API runtime, cost, or complete coverage."""
from __future__ import annotations
import math


def estimate(candidates:int,months:int=24,batch_size:int=8,articles_per_candidate:int=300):
    if min(candidates,months,batch_size,articles_per_candidate)<1:
        raise ValueError('Inputs must be positive integers.')
    mentions=candidates*articles_per_candidate
    return {
        'candidate_records':candidates,
        'monthly_windows':months,
        'names_per_query':batch_size,
        'initial_search_jobs_before_pagination':math.ceil(candidates/batch_size)*months,
        'assumed_article_candidate_mentions':mentions,
        'illustrative_uncompressed_body_gib_at_20kb_per_mention':round(mentions*20_000/1024**3,3),
        'notes':['Article overlap can reduce unique documents; versions can increase storage.',
                 'Pagination and result caps can increase requests beyond this initial count.',
                 'No API response-time, quota sufficiency, sample representativeness or coverage guarantee.']
    }

if __name__=='__main__':
    import argparse,json
    p=argparse.ArgumentParser();p.add_argument('--candidates',type=int,default=1000)
    p.add_argument('--months',type=int,default=24);p.add_argument('--batch-size',type=int,default=8)
    p.add_argument('--articles-per-candidate',type=int,default=300)
    a=p.parse_args();print(json.dumps(estimate(a.candidates,a.months,a.batch_size,a.articles_per_candidate),indent=2))
