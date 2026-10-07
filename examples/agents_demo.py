"""End-to-end SYNTHETIC fixture: no real candidates, articles or model validation."""
from pathlib import Path
from types import SimpleNamespace
import json
from charisma_lab.agents_store import AgentStore
from charisma_lab.agents import SentimentWorkflow,RunBudget
from charisma_lab.agents_collect import select_cohort
from charisma_lab.agents_analysis import FeatureConfig

class FixtureProvider:
    name='mediacloud'
    def page(self,p):
        rows=[]
        for d in p['domains']:
            for cid in p['candidate_ids']:
                name='Alex Rowan' if cid=='DEMO_H' else 'Jordan Vale'
                mood='praised' if d.startswith('national') else 'criticized'
                rows.append({'url':f'https://{d}/{cid}/{mood}',
                  'title':f'Congress candidate {name} {mood} over hospital budget proposal',
                  'published_at':'2026-09-20'})
        return rows,None,False

class FixtureAnnotator:
    model_id='synthetic_fixture_not_a_real_NLP_model'
    def predict(self,contexts):
        score=.6 if 'praised' in contexts[0] else -.6
        return dict(sentiment=score,confidence=.8,probabilities={'positive':.8 if score>0 else .2,'negative':.2 if score>0 else .8})


def run_demo(folder):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    path=folder/'SYNTHETIC_demo.sqlite'
    # Idempotent without deleting user data; only this explicitly named fixture file is used.
    with AgentStore(path) as s:
        for cid,name,office,state in [('DEMO_H','Alex Rowan','H','MI'),('DEMO_S','Jordan Vale','S','PA')]:
            s.candidate(cid,name,known_at='2020-01-01',source_url='synthetic://fixture')
            s.con.execute('INSERT OR IGNORE INTO cs_candidate_cycles VALUES(?,?,?,?,?,?,?,?,?,?)',
                (cid,2026,office,state,'1','SYNTHETIC',2026,'registry_only','2020-01-01','synthetic://fixture'))
            s.identity_link(cid,'person:'+cid,'synthetic://fixture','2020-01-01')
            s.term(person_id='person:'+cid,office=office,state=state,start_date='2025-01-03T00:00:00Z',
                   end_date='2027-01-03T00:00:00Z',available_at='2025-01-03',evidence_url='synthetic://fixture')
        for i,(d,scope,states) in enumerate([('national1.example','national',[]),('national2.example','national',[]),
                                          ('michigan1.example','state',['MI']),('michigan2.example','local',['MI']),
                                          ('pennsylvania1.example','state',['PA']),('pennsylvania2.example','metro',['PA'])],1):
            s.source_profile(domain=d,name=d,scope=scope,states=states,media_cloud_id=i,
                    valid_from='2020-01-01',observed_at='2020-01-01',evidence_url='synthetic://fixture')
        s.con.commit();workflow=SentimentWorkflow(s);cohort=select_cohort(s,max_candidates=None)
        workflow.collector.plan_campaign(cohort,'2026-09-01','2026-09-30',run_label='synthetic_fixture')
        report=workflow.run(cohort,'2026-10-06',run_network=True,provider_override=FixtureProvider(),
            client_override=SimpleNamespace(requests_used=0),annotator=FixtureAnnotator(),budget=RunBudget(),
            feature_config=FeatureConfig(mode='retrospective',reviewed_only=False,min_unique_articles=1,min_outlets=1))
        workflow.export(folder/'exports')
        summary=[{'label':'SYNTHETIC ONLY','name':r['name'],'office':'H' if r['candidate_id']=='DEMO_H' else 'S',
                  'national':r['national']['score'],'local':r['subnational']['score'],
                  'media_recency':r['media_recency_score'],'in_office':r['in_office_at_cutoff']} for r in report['features']]
        (folder/'SYNTHETIC_demo_summary.json').write_text(json.dumps(summary,indent=2))
        return summary

if __name__=='__main__':
    import tempfile
    print(json.dumps(run_demo(Path(tempfile.mkdtemp())/'demo'),indent=2))
