"""Synthetic FEC acquisition contracts. No live endpoint or DNS requests."""
import io
import json
import sqlite3
import zipfile
from types import SimpleNamespace

import pytest
import requests

from charisma_lab.agents_sources import download_fec_cycles, SourceAgent, FEC_BULK_HOST
from charisma_lab.agents_store import AgentStore
from charisma_lab.importers import FecAcquisitionError, import_fec_zip
from charisma_lab.network import BudgetExceeded, HttpClient, AccessBlocked
from charisma_lab.pilot import RequestLedger


def record(cid='SYNTHETIC_ONE',name='ROWAN, ALEX'):
    return '|'.join([cid,name,'SYNTHETIC','2026','MI','H','01']+['']*8)


def archive(*rows,member='cn.txt'):
    data=io.BytesIO()
    with zipfile.ZipFile(data,'w') as z:
        z.writestr(member,'\n'.join(rows)+'\n')
    return data.getvalue()


def response(status=200,content=b'',headers=None):
    result=requests.Response()
    result.status_code=status
    result._content=content
    result._content_consumed=True
    result.headers.update(headers or {})
    return result


class Session:
    def __init__(self,*responses):
        self.headers={}
        self.responses=iter(responses)
        self.calls=[]
    def get(self,url,**kwargs):
        self.calls.append((url,kwargs))
        return next(self.responses)


def test_permitted_redirects_share_durable_budget_and_valid_cache(tmp_path,monkeypatch):
    monkeypatch.setattr('charisma_lab.network.time.sleep',lambda _:None)
    session=Session(response(301,headers={'Location':'https://fec.gov/files/bulk-downloads/2026/cn26.zip'}),
        response(200,archive(record())))
    with AgentStore(tmp_path/'pilot.sqlite') as store:
        ledger=RequestLedger(store)
        client=HttpClient(max_requests=20,session=session,before_request=ledger.reserve)
        result=download_fec_cycles(store,client,[2026],tmp_path/'cache')
        assert result[0]['imported_rows']==1
        assert ledger.used==client.requests_used==len(session.calls)==2
        assert all(not kwargs['allow_redirects'] and kwargs['verify'] for _,kwargs in session.calls)
        assert store.rows('SELECT roster_status FROM cs_candidate_cycles')==[{'roster_status':'registry_only'}]
        download_fec_cycles(store,client,[2026],tmp_path/'cache')
        assert ledger.used==2
        assert store.rows('SELECT COUNT(*) n FROM cs_candidates')[0]['n']==1


@pytest.mark.parametrize('location',[
    'https://fec.gov.attacker.example/cn26.zip','https://unknown-cdn.example/cn26.zip',
    'http://www.fec.gov/cn26.zip','https://user:secret@www.fec.gov/cn26.zip',
    'https://www.fec.gov:8443/cn26.zip','https://www.fec.gov/cn26.zip?token=never-output',
])
def test_unapproved_redirect_target_is_not_requested_or_disclosed(tmp_path,location):
    session=Session(response(302,headers={'Location':location}))
    with AgentStore(tmp_path/'pilot.sqlite') as store:
        client=HttpClient(session=session)
        with pytest.raises(FecAcquisitionError) as caught:
            download_fec_cycles(store,client,[2026],tmp_path/'cache')
        assert caught.value.details=={'stage':'download','reason':'redirect_not_permitted','cycle':2026,'http_status':302}
        assert len(session.calls)==1
        assert location not in str(caught.value)
        assert 'never-output' not in json.dumps(caught.value.details)
        assert not list((tmp_path/'cache').iterdir())


def test_redirect_second_hop_cannot_exceed_durable_limit(tmp_path,monkeypatch):
    monkeypatch.setattr('charisma_lab.network.time.sleep',lambda _:None)
    session=Session(response(301,headers={'Location':'/other/cn26.zip'}))
    with AgentStore(tmp_path/'pilot.sqlite') as store:
        ledger=RequestLedger(store,1)
        client=HttpClient(max_requests=20,session=session,before_request=ledger.reserve)
        with pytest.raises(BudgetExceeded): download_fec_cycles(store,client,[2026],tmp_path/'cache')
        assert len(session.calls)==ledger.used==1
        assert store.rows('SELECT * FROM cs_candidates')==[]


@pytest.mark.parametrize('status,content,reason',[(404,b'secret-response','http_status'),
    (200,b'<html>secret-response</html>','response_not_zip')])
def test_download_diagnostics_include_safe_status_not_body(tmp_path,status,content,reason):
    session=Session(response(status,content))
    with AgentStore(tmp_path/'pilot.sqlite') as store:
        with pytest.raises(FecAcquisitionError) as caught:
            download_fec_cycles(store,HttpClient(session=session),[2026],tmp_path/'cache')
        assert caught.value.details=={'stage':'download','reason':reason,'cycle':2026,'http_status':status}
        assert 'secret-response' not in str(caught.value)+json.dumps(caught.value.details)


def test_later_malformed_row_rolls_back_every_new_candidate_and_cycle(tmp_path):
    path=tmp_path/'candidates.zip'
    path.write_bytes(archive(record(),record('SYNTHETIC_TWO','VALE, JORDAN'),'MALFORMED|SECRET-ROW'))
    db=tmp_path/'sentiment.sqlite'
    with AgentStore(db) as store:
        store.candidate('EXISTING','Prior Person',aliases=['Prior Othername'],known_at='2000-01-01',
            source_url='synthetic://existing',person_id='known-person')
        before=store.rows('SELECT * FROM cs_candidates')
        with pytest.raises(FecAcquisitionError) as caught: import_fec_zip(store,path,2026)
        assert caught.value.details=={'stage':'parse','reason':'field_count_mismatch','cycle':2026,'row':3,'field_count':2}
        assert 'SECRET-ROW' not in str(caught.value)
        assert store.rows('SELECT * FROM cs_candidates')==before
        assert store.rows('SELECT * FROM cs_candidate_cycles')==[]
    with AgentStore(db) as reopened:
        assert reopened.rows('SELECT * FROM cs_candidates')==before
        assert reopened.rows('SELECT * FROM cs_candidate_cycles')==[]


def test_failed_download_parse_is_not_promoted_to_cache(tmp_path):
    session=Session(response(200,archive(record(),'BROKEN|ROW')))
    with AgentStore(tmp_path/'pilot.sqlite') as store:
        with pytest.raises(FecAcquisitionError,match='parse/field_count_mismatch'):
            download_fec_cycles(store,HttpClient(session=session),[2026],tmp_path/'cache')
        assert store.rows('SELECT * FROM cs_candidates')==[]
        assert not list((tmp_path/'cache').iterdir())


def test_import_preserves_existing_identity_and_dated_provenance(tmp_path):
    path=tmp_path/'candidates.zip'
    path.write_bytes(archive(record('EXISTING','RENAMED, PERSON')))
    with AgentStore(tmp_path/'pilot.sqlite') as store:
        store.candidate('EXISTING','Prior Person',aliases=['Prior Othername'],known_at='2000-01-01',
            source_url='synthetic://existing',person_id='known-person')
        before=store.rows('SELECT * FROM cs_candidates')
        assert import_fec_zip(store,path,2026)==1
        assert store.rows('SELECT * FROM cs_candidates')==before
        assert store.rows('SELECT roster_status FROM cs_candidate_cycles')==[{'roster_status':'registry_only'}]


def test_pipe_file_quote_marks_do_not_swallow_fields_or_later_rows(tmp_path):
    path=tmp_path/'candidates.zip'
    path.write_bytes(archive(record(name='"ROWAN, ALEX'),record('SYNTHETIC_TWO','VALE, JORDAN')))
    with AgentStore(tmp_path/'pilot.sqlite') as store:
        assert import_fec_zip(store,path,2026)==2
        assert store.rows('SELECT COUNT(*) n FROM cs_candidates')[0]['n']==2


def test_candidate_name_validation_still_rejects_punctuation_aliases_atomically(tmp_path):
    path=tmp_path/'candidates.zip'
    path.write_bytes(archive(record(),record('SYNTHETIC_TWO','ROWAN, --')))
    with AgentStore(tmp_path/'pilot.sqlite') as store:
        with pytest.raises(FecAcquisitionError,match='parse/invalid_candidate_name'):
            import_fec_zip(store,path,2026)
        assert store.rows('SELECT * FROM cs_candidates')==[]


def test_invalid_zip_diagnostics_do_not_leak_archive_contents(tmp_path):
    path=tmp_path/'candidates.zip'
    path.write_bytes(b'PK not-a-valid-zip SECRET')
    with AgentStore(tmp_path/'pilot.sqlite') as store:
        with pytest.raises(FecAcquisitionError) as caught: import_fec_zip(store,path,2026)
        assert caught.value.details=={'stage':'archive','reason':'invalid_or_unsupported_zip','cycle':2026}
        assert 'SECRET' not in str(caught.value)


def test_official_production_bulk_object_charges_both_hops(tmp_path,monkeypatch):
    monkeypatch.setattr('charisma_lab.network.time.sleep',lambda _:None)
    target=f'https://{FEC_BULK_HOST}/bulk-downloads/2026/cn26.zip'
    session=Session(response(302,headers={'Location':target}),response(200,archive(record())))
    with AgentStore(tmp_path/'pilot.sqlite') as store:
        ledger=RequestLedger(store)
        client=HttpClient(max_requests=20,session=session,before_request=ledger.reserve)
        result=download_fec_cycles(store,client,[2026],tmp_path/'cache')
        assert result[0]['imported_rows']==1
        assert ledger.used==client.requests_used==len(session.calls)==2
        assert session.calls[1][0]==target


@pytest.mark.parametrize('target',[
    f'https://{FEC_BULK_HOST}.attacker.example/bulk-downloads/2026/cn26.zip',
    'https://different-bucket.s3-us-gov-west-1.amazonaws.com/bulk-downloads/2026/cn26.zip',
    f'https://{FEC_BULK_HOST}/bulk-downloads/2024/cn24.zip',
    f'https://{FEC_BULK_HOST}/bulk-downloads/2026/cn24.zip',
    f'https://{FEC_BULK_HOST}/other/2026/cn26.zip',
    f'https://{FEC_BULK_HOST}/bulk-downloads/2026/../2026/cn26.zip',
    f'https://{FEC_BULK_HOST}/bulk-downloads/2026/cn26.zip?secret=hidden',
    f'https://{FEC_BULK_HOST}/bulk-downloads/2026/cn26.zip#fragment',
    f'https://user:secret@{FEC_BULK_HOST}/bulk-downloads/2026/cn26.zip',
    f'http://{FEC_BULK_HOST}/bulk-downloads/2026/cn26.zip',
])
def test_production_bulk_redirect_is_exact_and_does_not_broaden_aws_access(tmp_path,target):
    session=Session(response(302,headers={'Location':target}))
    with AgentStore(tmp_path/'pilot.sqlite') as store:
        with pytest.raises(FecAcquisitionError) as caught:
            download_fec_cycles(store,HttpClient(session=session),[2026],tmp_path/'cache')
        assert caught.value.details['reason']=='redirect_not_permitted'
        assert len(session.calls)==1
        assert 'hidden' not in str(caught.value)+json.dumps(caught.value.details)


@pytest.mark.parametrize('status',[401,403])
def test_source_resolution_stops_after_access_denial_without_logging_secret(tmp_path,status):
    calls=[]
    def denied(*args,**kwargs):
        calls.append(1)
        error=AccessBlocked('SECRET must never appear in reports')
        error.http_status=status
        raise error
    with AgentStore(tmp_path/'pilot.sqlite') as store:
        for domain in ['one.example','two.example','three.example']:
            store.con.execute('INSERT INTO cs_outlets(domain,name) VALUES(?,?)',(domain,domain))
        store.con.commit()
        result=SourceAgent(store).resolve(SimpleNamespace(get=denied),'fixture-only-secret',max_sources=3)
        assert len(calls)==len(result)==1
        assert result[0]['http_status']==status and result[0]['status']=='error'
        assert 'SECRET' not in json.dumps(result)
        assert 'SECRET' not in json.dumps(store.rows('SELECT details_json FROM sa_events'))
