from __future__ import annotations
import argparse,csv,json,os
from pathlib import Path
import pandas as pd
from .store import Store
from . import importers
from .util import dumps,now


def parser():
    p=argparse.ArgumentParser(description='Candidate Standing Lab: research pipeline, not validated election probabilities.')
    p.add_argument('--db',default='Candidate_Standing.sqlite')
    sub=p.add_subparsers(dest='cmd',required=True)
    sub.add_parser('init'); sub.add_parser('status')
    r=sub.add_parser('import-funding');r.add_argument('path');r.add_argument('--cycles',type=int,nargs='+')
    r=sub.add_parser('import-fec');r.add_argument('path');r.add_argument('--cycle',type=int,required=True)
    r=sub.add_parser('download-fec');r.add_argument('--cycle',type=int,required=True);r.add_argument('--cache',default='raw')
    for table in ['candidates','aliases','roster','outlets','surveys','pedigree','articles','annotations']:
        r=sub.add_parser('import-'+table);r.add_argument('path')
    r=sub.add_parser('plan');r.add_argument('--provider',choices=['gdelt','mediacloud'],default='mediacloud')
    r.add_argument('--cycle',type=int);r.add_argument('--office',choices=['P','S','H']);r.add_argument('--ids',nargs='+')
    r.add_argument('--start',required=True);r.add_argument('--end',required=True);r.add_argument('--batch-size',type=int,default=8)
    r.add_argument('--max-candidates',type=int,default=24);r.add_argument('--source-ids',nargs='*',type=int)
    r.add_argument('--collection-ids',nargs='*',type=int);r.add_argument('--max-jobs',type=int,default=10000)
    r=sub.add_parser('resolve-outlets');r.add_argument('--max-requests',type=int,default=40)
    r=sub.add_parser('collect');r.add_argument('--provider',choices=['gdelt','mediacloud'],required=True)
    r.add_argument('--max-jobs',type=int,default=10);r.add_argument('--max-requests',type=int,default=20);r.add_argument('--checkpoint')
    r=sub.add_parser('fetch');r.add_argument('--max-articles',type=int,default=50);r.add_argument('--max-requests',type=int,default=120);r.add_argument('--checkpoint')
    r=sub.add_parser('annotate');r.add_argument('--max-pairs',type=int,default=100);r.add_argument('--device',type=int,default=-1)
    r.add_argument('--revision');r.add_argument('--checkpoint')
    r=sub.add_parser('score');r.add_argument('--ids',nargs='+',required=True);r.add_argument('--as-of',required=True)
    r.add_argument('--geography',required=True);r.add_argument('--population',required=True);r.add_argument('--election-id',default='research')
    r.add_argument('--mode',choices=['strict','research'],default='strict');r.add_argument('--reviewed-only',action='store_true')
    r=sub.add_parser('export');r.add_argument('--out',default='outputs')
    r=sub.add_parser('backup');r.add_argument('path')
    sub.add_parser('reset-interrupted');sub.add_parser('retry-failed')
    return p


def main(argv=None):
    args=parser().parse_args(argv)
    with Store(args.db) as store:
        cmd=args.cmd
        if cmd in {'init','status'}: result=store.status()
        elif cmd=='import-funding': result={'imported':importers.import_funding(store,args.path,args.cycles)}
        elif cmd=='import-fec': result={'imported':importers.import_fec_zip(store,args.path,args.cycle)}
        elif cmd=='download-fec':
            from .network import HttpClient
            if args.cycle%2 or not 1976<=args.cycle<=2100: raise ValueError('Use an even finance-cycle year')
            path=Path(args.cache)/f'cn{args.cycle%100:02d}.zip';path.parent.mkdir(parents=True,exist_ok=True)
            if not path.exists():
                url=f'https://www.fec.gov/files/bulk-downloads/{args.cycle}/cn{args.cycle%100:02d}.zip'
                r=HttpClient(max_requests=3).get(url,max_bytes=50_000_000)
                if r.status_code!=200: raise RuntimeError('FEC download did not return a file')
                temporary=path.with_suffix('.part');temporary.write_bytes(r.content);temporary.replace(path)
            result={'imported':importers.import_fec_zip(store,path,args.cycle),'cache_file':str(path)}
        elif cmd.startswith('import-'):
            result={'imported':getattr(importers,cmd.replace('-','_'))(store,args.path)}
        elif cmd=='resolve-outlets':
            from .collect import resolve_outlets
            from .network import HttpClient
            result=resolve_outlets(store,HttpClient(max_requests=args.max_requests),os.environ.get('MEDIACLOUD_API_KEY',''))
        elif cmd=='plan':
            from .collect import plan
            if args.ids: ids=args.ids
            else:
                if args.cycle is None: raise ValueError('Provide --ids or --cycle; no implicit all-history crawl.')
                sql='SELECT DISTINCT candidate_id FROM cs_candidate_cycles WHERE cycle=?';params=[args.cycle]
                if args.office: sql+=' AND office=?';params.append(args.office)
                sql+=' ORDER BY candidate_id LIMIT ?';params.append(args.max_candidates)
                ids=[r['candidate_id'] for r in store.rows(sql,params)]
            outlets=store.rows('SELECT * FROM cs_outlets')
            result=plan(store,ids,args.start,args.end,provider=args.provider,batch_size=args.batch_size,
                  domains=[r['domain'] for r in outlets],source_ids=args.source_ids or [r['media_cloud_id'] for r in outlets if r['media_cloud_id']],
                  collection_ids=args.collection_ids,max_jobs=args.max_jobs)
            result['selected_ids']=ids
            result['selection_note']='ID-sorted capped engineering pilot, NOT a representative research sample or confirmed ballot roster.'
        elif cmd=='collect':
            from .network import HttpClient
            from .collect import MediaCloudProvider,GdeltProvider,run_search
            client=HttpClient(max_requests=args.max_requests)
            provider=MediaCloudProvider(client,os.environ.get('MEDIACLOUD_API_KEY','')) if args.provider=='mediacloud' else GdeltProvider(client)
            result=run_search(store,provider,max_jobs=args.max_jobs,checkpoint_path=args.checkpoint)
        elif cmd=='fetch':
            from .network import HttpClient
            from .scrape import Scraper,run_fetch
            domains=[r['domain'] for r in store.rows('SELECT domain FROM cs_outlets WHERE permitted_fetch=1')]
            result=run_fetch(store,Scraper(HttpClient(max_requests=args.max_requests),domains),
                             max_articles=args.max_articles,checkpoint_path=args.checkpoint)
        elif cmd=='annotate':
            from .annotate import NLIAnnotator,annotate_pending
            result=annotate_pending(store,NLIAnnotator(revision=args.revision,device=args.device),
                                  max_pairs=args.max_pairs,checkpoint_path=args.checkpoint)
        elif cmd=='score':
            from .scoring import ScoreConfig,score_candidate
            domains=tuple(r['domain'] for r in store.rows('SELECT domain FROM cs_outlets ORDER BY domain'))
            cfg=ScoreConfig(require_reviewed=args.reviewed_only,outlet_domains=domains)
            result=[score_candidate(store,c,args.as_of,geography=args.geography,population=args.population,
                          election_id=args.election_id,mode=args.mode,config=cfg) for c in args.ids]
        elif cmd=='export':
            root=Path(args.out);root.mkdir(parents=True,exist_ok=True)
            tables=['cs_candidates','cs_candidate_cycles','cs_roster','cs_scores','cs_jobs','cs_outlets']
            for table in tables:
                pd.read_sql_query(f'SELECT * FROM {table}',store.con).to_csv(root/f'{table}.csv',index=False)
            pd.read_sql_query('''SELECT n.version_id,n.candidate_id,n.sentiment,n.confidence,n.entity_status,n.reviewed,
              n.model_id,n.evidence,a.url,a.outlet FROM cs_annotations n
              JOIN cs_versions v USING(version_id) JOIN cs_articles a USING(article_id)''',store.con).to_csv(root/'annotation_review.csv',index=False)
            result={'output_directory':str(root),'note':'No full article text is exported.'}
        elif cmd=='backup': result={'backup':str(store.backup(args.path))}
        elif cmd=='reset-interrupted': store.reset_interrupted();result=store.status()
        elif cmd=='retry-failed':
            from .collect import requeue_failed
            requeue_failed(store);result=store.status()
        else: raise ValueError(cmd)
        print(dumps(result))

if __name__=='__main__': main()
