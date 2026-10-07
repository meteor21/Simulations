"""Cooperative, bounded three-agent orchestrator. No hidden background service."""
from __future__ import annotations
import csv
import json
from dataclasses import dataclass,asdict
from pathlib import Path
from .agents_store import AgentStore
from .agents_sources import SourceAgent
from .agents_collect import CollectionAgent
from .agents_analysis import AnalysisAgent,FeatureConfig
from .network import HttpClient
from .collect import MediaCloudProvider,GdeltProvider
from .util import now,dumps

@dataclass
class RunBudget:
    max_requests:int=20
    max_search_jobs:int=10
    max_fetch_articles:int=10
    max_annotation_pairs:int=100
    resolve_sources:int=0
    def __post_init__(self):
        if any(type(v) is not int for v in asdict(self).values()): raise ValueError('Budgets must be integers')
        if self.max_requests<1: raise ValueError('max_requests must be positive')
        if any(v<0 for k,v in asdict(self).items() if k!='max_requests'): raise ValueError('Budgets cannot be negative')

class SentimentWorkflow:
    """One SQLite writer; agents cooperate in phases rather than evade rate limits.

    SourceAgent audits/resolves -> CollectionAgent retrieves/pages/splits/fetches ->
    AnalysisAgent annotates/reviews/summarizes. API jobs and events survive restarts.
    No paid LLM/API calls are made implicitly. No task runs after this process exits.
    """
    def __init__(self,store:AgentStore):
        self.store=store; self.sources=SourceAgent(store)
        self.collector=CollectionAgent(store); self.analyst=AnalysisAgent(store)

    def run(self,cohort,as_of,*,budget=None,run_network=False,provider='mediacloud',
            token=None,annotator=None,fetch=False,feature_config=None,checkpoint_path=None,
            client_override=None,provider_override=None):
        budget=budget or RunBudget(); report={'started_at':now(),'budgets':asdict(budget)}
        self.store.event('Coordinator','run_start',network_enabled=run_network,**asdict(budget))
        try:
            report['sources']=self.sources.audit()
            if run_network:
                client=client_override or HttpClient(max_requests=budget.max_requests)
                if hasattr(client,'max_requests'):
                    client.max_requests=min(client.max_requests,client.requests_used+budget.max_requests)
                if provider=='mediacloud' and not token and provider_override is None:
                    raise ValueError('Set MEDIACLOUD_API_KEY in Colab Secrets before enabling Media Cloud')
                if budget.resolve_sources:
                    report['source_resolution']=self.sources.resolve(client,token,max_sources=budget.resolve_sources)
                service=provider_override or (MediaCloudProvider(client,token) if provider=='mediacloud' else GdeltProvider(client))
                report['collection']=self.collector.run(service,max_jobs=budget.max_search_jobs,checkpoint_path=checkpoint_path)
                if fetch: report['full_text']=self.collector.scrape(client,max_articles=budget.max_fetch_articles,checkpoint_path=checkpoint_path)
                report['http_requests_used']=client.requests_used
            else: report['collection']={'status':'disabled','note':'No live requests were made'}
            if annotator is not None:
                report['annotation']=self.analyst.annotate(annotator,max_pairs=budget.max_annotation_pairs)
            else: report['annotation']={'status':'disabled','note':'Import reviewed annotations or opt into local model download'}
            report['features']=self.analyst.features(cohort,as_of,feature_config or FeatureConfig()) if cohort else []
            report['queue']=self.collector.queue_status()
            report['finished_at']=now()
            self.store.event('Coordinator','run_complete',features=len(report['features']))
            return report
        except Exception as exc:
            self.store.event('Coordinator','run_error',error_type=type(exc).__name__)
            raise
        finally:
            if checkpoint_path: self.store.backup(checkpoint_path)

    def export(self,folder):
        folder=Path(folder); folder.mkdir(parents=True,exist_ok=True)
        tables={'source_profiles':'sa_source_profiles','source_bias_assessments':'sa_bias_assessments',
                'candidate_registry':'cs_candidates','candidate_cycles':'cs_candidate_cycles',
                'service_terms':'sa_service_terms','source_coverage':'sa_source_coverage','plan_audit':'sa_plan_audit','agent_events':'sa_events'}
        for name,table in tables.items():
            rows=self.store.rows(f'SELECT * FROM {table}')
            columns=[r[1] for r in self.store.con.execute(f'PRAGMA table_info({table})')]
            with open(folder/(name+'.csv'),'w',newline='',encoding='utf-8') as f:
                writer=csv.DictWriter(f,fieldnames=columns);writer.writeheader();writer.writerows(rows)
        snapshots=[json.loads(r['features_json']) for r in self.store.rows('SELECT * FROM sa_snapshots')]
        with open(folder/'candidate_sentiment_features.jsonl','w',encoding='utf-8') as f:
            for row in snapshots: f.write(dumps(row)+'\n')
        # Readable narrow features without the nested diagnostic objects.
        flat=[]
        for r in snapshots:
            flat.append({k:r.get(k) for k in ['candidate_id','name','cycle','state','as_of','mode','reviewed_only','media_recency_score','local_minus_national','momentum_30d_vs_previous30d','in_office_at_cutoff']} |
                {'national_score':r['national']['score'],'subnational_score':r['subnational']['score'],
                 'flags_json':dumps(r['flags'])})
        columns=list(flat[0]) if flat else ['candidate_id','as_of','media_recency_score','flags_json']
        with open(folder/'candidate_sentiment_summary.csv','w',newline='',encoding='utf-8') as f:
            w=csv.DictWriter(f,fieldnames=columns);w.writeheader();w.writerows(flat)
        coverage=self.store.rows('''SELECT a.outlet,substr(v.published_at,1,4) AS publication_year,
            COUNT(DISTINCT a.article_id) AS observed_urls,COUNT(*) AS stored_versions,
            SUM(CASE WHEN length(v.body_z)>0 THEN 1 ELSE 0 END) AS versions_with_body,
            MIN(v.published_at) AS earliest_observed_publication,
            MAX(v.published_at) AS latest_observed_publication
            FROM cs_articles a JOIN cs_versions v USING(article_id)
            GROUP BY a.outlet,substr(v.published_at,1,4) ORDER BY a.outlet,publication_year''')
        columns=list(coverage[0]) if coverage else ['outlet','publication_year','observed_urls','stored_versions','versions_with_body','earliest_observed_publication','latest_observed_publication']
        with open(folder/'observed_source_year_coverage.csv','w',newline='',encoding='utf-8') as f:
            w=csv.DictWriter(f,fieldnames=columns);w.writeheader();w.writerows(coverage)
        review=self.analyst.review_queue(1000)
        (folder/'annotation_review.json').write_text(json.dumps(review,indent=2,ensure_ascii=False))
        (folder/'queue_status.json').write_text(json.dumps(self.collector.queue_status(),indent=2))
        (folder/'DATA_WARNING.txt').write_text('Media portrayal is not representative public opinion. Missing is not neutral.\nNo raw full article bodies are included in these exports. Review evidence may be copyrighted; keep private.\nStrict and retrospective snapshots must not be mixed in forecast evaluation.\n')
        return folder
