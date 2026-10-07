from datetime import datetime,timedelta,timezone
import json
import pytest
from charisma_lab.collect import plan,run_search,MediaCloudProvider,GdeltProvider,query_names
from charisma_lab.network import AccessBlocked,BudgetExceeded,HttpClient,require_public_url
from charisma_lab.annotate import target_context,NLIAnnotator,annotate_pending
from charisma_lab.util import now


def test_plan_idempotent_batched(store):
    store.candidate('C2','Jordan Vale',known_at='2020-01-01',source_url='synthetic://test')
    a=plan(store,['C1','C2'],'2022-10-01','2024-10-01T00:00:00Z',source_ids=[1],batch_size=2)
    b=plan(store,['C1','C2'],'2022-10-01','2024-10-01T00:00:00Z',source_ids=[1],batch_size=2)
    assert a['initial_jobs']==24 and b['new_jobs']==0
    assert 'scandal' not in query_names(store,['C1']).lower()

def test_plan_hard_cap(store):
    with pytest.raises(ValueError):plan(store,['C1'],'2022-10-01','2024-10-01',source_ids=[1],max_jobs=1)

def test_historical_gdelt_fails_explicitly(store):
    with pytest.raises(ValueError,match='89 days'):plan(store,['C1'],'2008-01-01','2008-10-01',provider='gdelt')

def test_media_cloud_requires_panel(store):
    with pytest.raises(ValueError,match='source_ids'):plan(store,['C1'],'2024-09-01','2024-09-30')

class FakeProvider:
    name='mediacloud'
    def page(self,p):
        if p.get('cursor'):return [],None,False
        return [{'url':'https://news.example/a','title':'Alex Rowan Senate campaign',
                 'published_at':'2024-09-01','metadata':{'synthetic':True}}],'next',False


def test_pagination_resume(store):
    plan(store,['C1'],'2024-09-01','2024-09-30',source_ids=[1])
    a=run_search(store,FakeProvider(),max_jobs=1)
    assert a['processed']==1
    assert store.con.execute("SELECT COUNT(*) FROM cs_jobs WHERE status='pending'").fetchone()[0]==1
    run_search(store,FakeProvider(),max_jobs=5)
    assert store.con.execute("SELECT COUNT(*) FROM cs_jobs WHERE status='pending'").fetchone()[0]==0
    assert store.con.execute('SELECT COUNT(*) FROM cs_articles').fetchone()[0]==1

def test_access_block_is_not_success(store):
    class Denied(FakeProvider):
        def page(self,p):raise AccessBlocked('denied')
    plan(store,['C1'],'2024-09-01','2024-09-30',source_ids=[1])
    result=run_search(store,Denied())
    assert result['blocked']==1 and store.rows('SELECT status FROM cs_jobs')[0]['status']=='blocked'

def test_request_budget_leaves_pending(store):
    class Exhausted(FakeProvider):
        def page(self,p):raise BudgetExceeded('done')
    plan(store,['C1'],'2024-09-01','2024-09-30',source_ids=[1])
    run_search(store,Exhausted())
    assert store.rows('SELECT status FROM cs_jobs')[0]['status']=='pending'

def test_interrupted_queue_reset(store):
    plan(store,['C1'],'2024-09-01','2024-09-30',source_ids=[1])
    store.con.execute("UPDATE cs_jobs SET status='running'");store.con.commit();store.reset_interrupted()
    assert store.rows('SELECT status FROM cs_jobs')[0]['status']=='pending'

def test_capped_search_splits_before_ingesting(store):
    class Saturated:
        name='gdelt'
        def page(self,p):return [],None,True
    end=datetime.now(timezone.utc);start=end-timedelta(days=1)
    plan(store,['C1'],start.isoformat(),end.isoformat(),provider='gdelt')
    run_search(store,Saturated(),max_jobs=1)
    assert store.con.execute("SELECT COUNT(*) FROM cs_jobs WHERE status='pending'").fetchone()[0]==2
    assert store.con.execute('SELECT COUNT(*) FROM cs_articles').fetchone()[0]==0

class FakeResponse:
    def __init__(self,payload):self.payload=payload
    def json(self):return self.payload

class FakeHttp:
    def __init__(self,payload):self.payload=payload;self.calls=[]
    def get(self,url,**kw):self.calls.append((url,kw));return FakeResponse(self.payload)


def test_mediacloud_wire_contract():
    http=FakeHttp({'stories':[{'url':'https://a.example/a','title':'t','publish_date':'2024-01-02','indexed_date':'2024-01-03T00:00:00Z'}],'pagination_token':'abc'})
    p=dict(query='"Alex Rowan"',start='2024-01-01',end='2024-02-01',source_ids=[42],collection_ids=[],cursor=None)
    rows,token,cap=MediaCloudProvider(http,'secret').page(p)
    assert token=='abc' and rows[0]['published_at']=='2024-01-02'
    assert http.calls[0][1]['params']['ss']=='42' and http.calls[0][1]['headers']['Authorization']=='Token secret'

def test_provider_schema_mismatch_not_empty():
    http=FakeHttp({'error':'oops'})
    p=dict(query='x',start='2024-01-01',end='2024-02-01',source_ids=[1],collection_ids=[],cursor=None)
    with pytest.raises(ValueError):MediaCloudProvider(http,'key').page(p)

def test_target_masking_and_no_surname_only():
    text='Senator Alex Rowan proposed a bill. Rowan received criticism.'
    masked,evidence=target_context(text,['Alex Rowan'])
    assert 'Alex Rowan' not in masked[0] and 'Rowan received criticism.' in masked[0] and 'Alex Rowan' in evidence
    assert target_context('Rowan proposed a bill.',['Alex Rowan'])[0]==[]

class FakePipeline:
    def __call__(self,contexts,candidate_labels,**kw):
        return [{'labels':candidate_labels,'scores':[.8,.1,.1]} for _ in contexts]

def test_nli_adapter_without_download(store):
    vid=store.article(url='https://news.example/x',title='Senator Alex Rowan explains proposal',
       candidate_ids=['C1'],published_at='2024-01-01',retrieved_at='2024-01-02')
    store.con.commit()
    engine=NLIAnnotator(pipeline_override=FakePipeline())
    r=annotate_pending(store,engine)
    row=store.rows('SELECT * FROM cs_annotations')[0]
    assert r['annotated']==1 and row['sentiment']==pytest.approx(.7)
    assert row['reviewed']==0 and row['entity_status']=='exact_name_context'
    assert annotate_pending(store,engine)['annotated']==0

def test_common_full_name_requires_review(store):
    store.candidate('C2','Alex Rowan',known_at='2020-01-01',source_url='synthetic://other')
    store.article(url='https://news.example/x',title='Senator Alex Rowan explains proposal',candidate_ids=['C1'],retrieved_at=now())
    store.con.commit()
    annotate_pending(store,NLIAnnotator(pipeline_override=FakePipeline()))
    assert store.rows('SELECT entity_status FROM cs_annotations')[0]['entity_status']=='needs_review'

def test_http_budget_before_network():
    h=HttpClient(max_requests=1);h.requests_used=1
    with pytest.raises(BudgetExceeded):h.get('https://example.com')

def test_private_network_block(monkeypatch):
    monkeypatch.setattr('socket.getaddrinfo',lambda *a,**k:[(2,1,6,'',('127.0.0.1',80))])
    with pytest.raises(AccessBlocked):require_public_url('http://example.com')
