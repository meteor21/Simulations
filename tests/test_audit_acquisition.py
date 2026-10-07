"""Offline regressions for acquisition limits, resumability, and database safety."""
import sqlite3
import sys
from types import SimpleNamespace

import pytest
import requests
from requests.adapters import HTTPAdapter

from charisma_lab.agents_collect import select_cohort
from charisma_lab.collect import plan, resolve_outlets, run_search
from charisma_lab.network import AccessBlocked, BudgetExceeded, HttpClient
from charisma_lab.scrape import Scraper
from charisma_lab.store import Store
from charisma_lab.util import iso


class Session:
    def __init__(self, responses):
        self.responses=iter(responses)
        self.headers={}
        self.calls=[]

    def get(self, url, **kwargs):
        self.calls.append((url,kwargs))
        value=next(self.responses)
        if isinstance(value,Exception): raise value
        return value


def response(status=200, body=b'ok', headers=None):
    r=requests.Response()
    r.status_code=status
    r.headers.update(headers or {})
    r._content=body
    r._content_consumed=True
    return r


def test_retries_consume_budget_and_durable_reservations(monkeypatch):
    monkeypatch.setattr('charisma_lab.network.time.sleep',lambda _:None)
    reserved=[]
    session=Session([response(429),requests.Timeout('a credential must not be printed')])
    client=HttpClient(max_requests=2,interval=0,session=session,before_request=lambda:reserved.append(1))
    with pytest.raises(BudgetExceeded): client.get('https://provider.example/search')
    assert len(session.calls)==client.requests_used==len(reserved)==2
    assert all(not call[1]['allow_redirects'] for call in session.calls)


def test_persistent_reservation_failure_prevents_request():
    def exhausted(): raise BudgetExceeded('Persistent pilot cap reached')
    session=Session([])
    client=HttpClient(session=session,before_request=exhausted)
    with pytest.raises(BudgetExceeded): client.get('https://provider.example/search')
    assert client.requests_used==0 and session.calls==[]


def test_requests_adapter_cannot_retry_outside_counter():
    session=requests.Session()
    session.mount('https://',HTTPAdapter(max_retries=8))
    HttpClient(session=session)
    assert session.adapters['https://'].max_retries.total==0


@pytest.mark.parametrize('limit',[True,1.5,0,-1])
def test_http_budget_requires_positive_integer(limit):
    with pytest.raises(ValueError): HttpClient(max_requests=limit)


def test_robots_and_redirect_share_hard_budget(monkeypatch):
    monkeypatch.setitem(sys.modules,'trafilatura',SimpleNamespace())
    monkeypatch.setattr('charisma_lab.scrape.require_public_url',lambda url:None)
    monkeypatch.setattr('charisma_lab.network.time.sleep',lambda _:None)
    session=Session([response(404),response(302,headers={'Location':'/next'})])
    client=HttpClient(max_requests=2,interval=0,session=session)
    scraper=Scraper(client,['news.example'])
    with pytest.raises(BudgetExceeded): scraper.fetch('https://news.example/story')
    assert [url for url,_ in session.calls]==['https://news.example/robots.txt','https://news.example/story']
    assert client.requests_used==2


def test_redirect_to_unapproved_domain_does_not_fetch(monkeypatch):
    monkeypatch.setitem(sys.modules,'trafilatura',SimpleNamespace())
    monkeypatch.setattr('charisma_lab.scrape.require_public_url',lambda url:None)
    monkeypatch.setattr('charisma_lab.network.time.sleep',lambda _:None)
    session=Session([response(404),response(302,headers={'Location':'https://private.example/article'})])
    client=HttpClient(max_requests=20,interval=0,session=session)
    with pytest.raises(AccessBlocked,match='not opted in'):
        Scraper(client,['news.example']).fetch('https://news.example/story')
    assert client.requests_used==2


def test_robots_request_rate_honored_and_cached(monkeypatch):
    monkeypatch.setattr('charisma_lab.scrape.require_public_url',lambda url:None)
    session=Session([response(body=b'User-agent: *\nRequest-rate: 1/60\nAllow: /\n')])
    client=HttpClient(session=session)
    scraper=Scraper(client,['news.example'])
    assert scraper.allowed('https://news.example/a')==60
    assert scraper.allowed('https://news.example/b')==60
    assert client.requests_used==1


def test_database_schema_checked_before_any_mutation(tmp_path):
    path=tmp_path/'future.sqlite'
    with sqlite3.connect(path) as con:
        con.execute('CREATE TABLE cs_meta(key TEXT PRIMARY KEY,value TEXT)')
        con.execute("INSERT INTO cs_meta VALUES('schema_version','999')")
    before=path.read_bytes()
    with pytest.raises(ValueError,match='Incompatible'): Store(path)
    assert path.read_bytes()==before
    assert not (tmp_path/'future.sqlite-wal').exists()
    with sqlite3.connect(path) as con:
        assert con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()==[('cs_meta',)]


def test_backup_refuses_election_database_and_preserves_fixed_tmp(store,tmp_path):
    target=tmp_path/'elections.sqlite'
    with sqlite3.connect(target) as con:
        con.execute('CREATE TABLE election_results(candidate TEXT)')
        con.execute("INSERT INTO election_results VALUES('preserve')")
    before=target.read_bytes()
    with pytest.raises(ValueError,match='dedicated'): store.backup(target)
    assert target.read_bytes()==before
    target=tmp_path/'checkpoint.sqlite'
    fixed_tmp=tmp_path/'checkpoint.sqlite.tmp'
    fixed_tmp.write_text('existing user file')
    store.backup(target)
    store.backup(target)
    assert fixed_tmp.read_text()=='existing user file'
    with sqlite3.connect(target) as con:
        assert con.execute('SELECT candidate_id FROM cs_candidates').fetchall()==[('C1',)]


def test_backup_refuses_other_project_database(store,tmp_path):
    target=tmp_path/'other.sqlite'
    with Store(target) as other:
        other.candidate('C2','Jordan Vale',source_url='synthetic://other')
    before=target.read_bytes()
    with pytest.raises(ValueError,match='another database'): store.backup(target)
    assert target.read_bytes()==before


def test_candidate_identity_cannot_be_silently_reassigned(store):
    store.candidate('C1','Alex Rowan',person_id='person-one',source_url='synthetic://one')
    with pytest.raises(ValueError,match='Conflicting person_id'):
        store.candidate('C1','Alex Rowan',person_id='person-two',source_url='synthetic://two')
    assert store.rows("SELECT person_id FROM cs_candidates WHERE candidate_id='C1'")[0]['person_id']=='person-one'


def test_directory_truncation_does_not_claim_unique_match(store):
    store.con.execute("INSERT INTO cs_outlets(domain,name) VALUES('news.example','News')")
    class Directory:
        def get(self,*args,**kwargs):
            return SimpleNamespace(json=lambda:{'results':[{'id':1,'homepage':'https://news.example'}],'next':'another-page'})
    report=resolve_outlets(store,Directory(),'never-output-this-token',max_pages=1)
    assert report[0]['status']=='incomplete_directory_search'
    assert store.rows('SELECT media_cloud_id FROM cs_outlets')[0]['media_cloud_id'] is None


def test_pagination_cycles_are_explicit_errors(store):
    class Cyclic:
        name='mediacloud'
        def page(self,p):
            return [],'B' if p['cursor']=='A' else 'A',False
    plan(store,['C1'],'2024-09-01','2024-09-30',source_ids=[1])
    result=run_search(store,Cyclic(),max_jobs=5)
    assert result['processed']==2 and result['errors']==1
    assert store.rows("SELECT COUNT(*) n FROM cs_jobs WHERE status='error'")[0]['n']==1


def test_failed_page_rolls_back_articles_and_reported_hits(store):
    class BrokenPage:
        name='mediacloud'
        def page(self,p):
            return [dict(url='https://news.example/good',title='Alex Rowan proposal'),
                    dict(url='https://news.example/bad',title='Alex Rowan response',published_at='malformed-date')],None,False
    plan(store,['C1'],'2024-09-01','2024-09-30',source_ids=[1])
    result=run_search(store,BrokenPage())
    assert result['errors']==1 and result['processed_hits']==0
    assert store.rows('SELECT * FROM cs_articles')==[]
    assert store.rows('SELECT * FROM cs_versions')==[]


def test_cohort_preserves_distinct_races_and_cutoff(store):
    for eid,stage,date in [('primary','primary','2026-01-01'),('general','general','2026-07-01')]:
        store.con.execute('INSERT INTO cs_roster VALUES(?,?,?,?,?,?,?,?,?)',
            ('C1',eid,2026,'H','MI','01',stage,iso(date),'synthetic://roster'))
    store.con.commit()
    rows=select_cohort(store,roster_only=True,max_candidates=None)
    assert {r['election_id'] for r in rows}=={'primary','general'}
    rows=select_cohort(store,roster_only=True,max_candidates=None,as_of='2026-06-01')
    assert [r['election_id'] for r in rows]==['primary']
    store.con.execute('UPDATE cs_candidates SET known_at=?',(iso('2026-06-02'),))
    assert select_cohort(store,roster_only=True,as_of='2026-06-01')==[]


def test_feed_generator_candidates_are_not_consumed_per_row(store,monkeypatch):
    from charisma_lab.agents_rss import collect_feed
    store.candidate('C2','Jordan Vale',source_url='synthetic://candidate')
    store.event=lambda *args,**kwargs:None
    monkeypatch.setattr(Scraper,'allowed',lambda self,url:0)
    feed=b'<rss><channel><item><title>Jordan Vale presents proposal</title><link>https://news.example/story</link></item></channel></rss>'
    client=SimpleNamespace(get=lambda *args,**kwargs:SimpleNamespace(status_code=200,content=feed))
    result=collect_feed(store,client,'https://news.example/feed',(cid for cid in ['C1','C2']),
        allowed_domains=['news.example'],rights_note='Synthetic permission fixture')
    assert result['matched_items']==1
    assert store.rows('SELECT candidate_id FROM cs_article_candidates')==[{'candidate_id':'C2'}]


def test_feed_zero_limit_does_not_request(store):
    from charisma_lab.agents_rss import collect_feed
    result=collect_feed(store,None,'https://news.example/feed',['C1'],allowed_domains=['news.example'],
        rights_note='Synthetic permission fixture',max_items=0)
    assert result['matched_items']==0
    with pytest.raises(ValueError,match='max_items'):
        collect_feed(store,None,'https://news.example/feed',['C1'],allowed_domains=['news.example'],
            rights_note='Synthetic permission fixture',max_items=-1)


def test_annotation_backdating_requires_explicit_record_evidence(store):
    import json
    vid=store.article(url='https://news.example/annotation',title='Alex Rowan proposal',candidate_ids=['C1'])
    with pytest.raises(ValueError,match='Backdating an annotation'):
        store.annotation(vid,'C1',0.2,evidence='Alex Rowan proposal',annotated_at='2000-01-01')
    with pytest.raises(ValueError,match='Backdating an annotation'):
        store.annotation(vid,'C1',0.2,evidence='Alex Rowan proposal',annotated_at='2000-01-01',
            annotation_basis='verified_annotation_record')
    store.annotation(vid,'C1',0.2,evidence='Alex Rowan proposal',annotated_at='2000-01-01',
        annotation_basis='synthetic_fixture',annotation_evidence_url='synthetic://annotation')
    row=store.rows('SELECT annotated_at,diagnostics_json FROM cs_annotations')[0]
    assert row['annotated_at']==iso('2000-01-01')
    assert json.loads(row['diagnostics_json'])['annotation_basis']=='synthetic_fixture'
