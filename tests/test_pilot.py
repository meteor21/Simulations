"""Bounded pilot regressions; all people and network transports here are synthetic."""
import csv
import json
from types import SimpleNamespace
import pytest
from charisma_lab.agents_store import AgentStore
from charisma_lab.network import BudgetExceeded, HttpClient
from charisma_lab.pilot import RequestLedger, prepare_pilot, run_pilot


def seed(store, n=24):
    for i in range(n):
        cid = f'SYNTHETIC_{i}'
        store.candidate(cid, f'Fixture Person{i}', known_at='2026-01-01', source_url='synthetic://fixture')
        store.con.execute('INSERT INTO cs_candidate_cycles VALUES(?,?,?,?,?,?,?,?,?,?)',
            (cid, 2026, 'H' if i % 2 else 'S', 'MI' if i % 2 else 'PA', str(i), 'SYNTHETIC',
             2026, 'registry_only', '2026-01-01', 'synthetic://fixture'))
    store.con.commit()


def test_durable_budget_cannot_reset_or_grow(tmp_path):
    db = tmp_path / 'pilot.sqlite'
    with AgentStore(db) as store:
        ledger = RequestLedger(store)
        for _ in range(19): ledger.reserve()
        assert ledger.used == 19
    with AgentStore(db) as store:
        ledger = RequestLedger(store)
        ledger.reserve()
        with pytest.raises(BudgetExceeded): ledger.reserve()
        assert ledger.used == 20
        with pytest.raises(ValueError): RequestLedger(store, 21)
        with pytest.raises(ValueError): RequestLedger(store, 19)


def test_budget_atomic_across_connections(tmp_path):
    with AgentStore(tmp_path / 'pilot.sqlite') as a, AgentStore(tmp_path / 'pilot.sqlite') as b:
        x, y = RequestLedger(a, 1), RequestLedger(b, 1)
        x.reserve()
        with pytest.raises(BudgetExceeded): y.reserve()
        assert y.used == 1


def test_transport_retries_reserve_every_attempt(tmp_path, monkeypatch):
    monkeypatch.setattr('charisma_lab.network.time.sleep', lambda _: None)
    class Response:
        headers = {}
        def __init__(self, status): self.status_code = status
        def close(self): pass
        def iter_content(self, size): yield b'{}'
    class Session:
        headers = {}
        def __init__(self): self.calls = 0
        def get(self, *a, **kw):
            self.calls += 1
            return Response(503 if self.calls == 1 else 200)
    session = Session()
    with AgentStore(tmp_path / 'p.sqlite') as store:
        ledger = RequestLedger(store, 2)
        client = HttpClient(max_requests=20, interval=0, session=session, before_request=ledger.reserve)
        client.get('https://provider.example/fixture')
        assert ledger.used == 2 == session.calls
        restarted = HttpClient(max_requests=20, interval=0, session=session, before_request=ledger.reserve)
        with pytest.raises(BudgetExceeded): restarted.get('https://provider.example/fixture')
        assert session.calls == 2


def test_prepare_exports_24_sourced_rows_and_preserves_registration_status(tmp_path):
    with AgentStore(tmp_path / 'p.sqlite') as store:
        seed(store, 30)
        cohort, plan = prepare_pilot(store, tmp_path / 'out')
        rows = list(csv.DictReader((tmp_path / 'out/selected_congressional_cohort.csv').open()))
        assert len(rows) == len(cohort) == 24
        assert len({r['candidate_id'] for r in rows}) == 24
        assert all(r['roster_status'] == 'registry_only' for r in rows)
        assert all(r['source_url'] == 'synthetic://fixture' for r in rows)
        assert plan['membership'] == 'registration_discovery_only'
        assert plan['status'] == 'prepared'


def test_missing_candidates_never_fabricated(tmp_path):
    with AgentStore(tmp_path / 'p.sqlite') as store:
        cohort, plan = prepare_pilot(store, tmp_path / 'out')
        assert cohort == []
        assert plan['status'] == 'blocked_missing_candidate_registry'
        assert list(csv.DictReader((tmp_path / 'out/selected_congressional_cohort.csv').open())) == []


def test_missing_credential_blocks_even_fec_download(tmp_path, monkeypatch):
    monkeypatch.delenv('MEDIACLOUD_API_KEY', raising=False)
    monkeypatch.setattr(HttpClient, 'get', lambda *a, **kw: pytest.fail('No live request permitted'))
    report = run_pilot(tmp_path / 'out', run_network=True, download_fec=True)
    assert report['status'] == 'blocked'
    assert report['http_attempts_total'] == 0
    assert any('MEDIACLOUD_API_KEY' in s for s in report['blockers'])


def test_insufficient_cohort_blocks_provider_with_credential(tmp_path, monkeypatch):
    monkeypatch.setenv('MEDIACLOUD_API_KEY', 'fixture-secret-not-real')
    monkeypatch.setattr(HttpClient, 'get', lambda *a, **kw: pytest.fail('No provider request permitted'))
    output = tmp_path / 'out'
    output.mkdir()
    with AgentStore(output / 'pilot.sqlite') as store: seed(store, 23)
    report = run_pilot(output, run_network=True)
    assert report['selected_candidates'] == 23
    assert report['http_attempts_total'] == 0
    assert 'fixture-secret-not-real' not in (output / 'pilot_report.json').read_text()


def test_offline_prepares_without_any_network(tmp_path, monkeypatch):
    monkeypatch.setattr(HttpClient, 'get', lambda *a, **kw: pytest.fail('Offline means no network'))
    output = tmp_path / 'out'
    output.mkdir()
    with AgentStore(output / 'pilot.sqlite') as store: seed(store)
    result = run_pilot(output)
    assert result['status'] == 'offline_prepared'
    assert result['http_attempts_total'] == 0

@pytest.mark.parametrize('value', ['not-a-number', '-1', '21', None])
def test_corrupt_or_removed_ledger_fails_closed(tmp_path, value):
    with AgentStore(tmp_path / 'p.sqlite') as store:
        ledger = RequestLedger(store)
        ledger.reserve()
        if value is None:
            store.con.execute("DELETE FROM cs_meta WHERE key='pilot_requests_used'")
        else:
            store.con.execute("UPDATE cs_meta SET value=? WHERE key='pilot_requests_used'", (value,))
        store.con.commit()
        with pytest.raises(ValueError): RequestLedger(store)
        with pytest.raises(ValueError): ledger.reserve()


def test_all_contest_memberships_exported_for_selected_ids(tmp_path):
    with AgentStore(tmp_path / 'p.sqlite') as store:
        seed(store)
        for i in range(24):
            for stage in ('primary', 'general'):
                store.con.execute('INSERT INTO cs_roster VALUES(?,?,?,?,?,?,?,?,?)',
                    (f'SYNTHETIC_{i}', f'fixture-{stage}-{i}', 2026, 'H', 'MI', str(i), stage,
                     '2026-01-01', 'synthetic://fixture'))
        store.con.commit()
        cohort, plan = prepare_pilot(store, tmp_path / 'out', roster_only=True)
        rows = list(csv.DictReader((tmp_path / 'out/selected_contest_memberships.csv').open()))
        assert len(cohort) == 24 and len(rows) == 48
        assert {r['stage'] for r in rows} == {'primary', 'general'}


def test_workflow_caps_an_oversized_override_client(tmp_path):
    from charisma_lab.agents import SentimentWorkflow, RunBudget
    class Response:
        status_code = 200
        headers = {}
        def close(self): pass
        def iter_content(self, size): yield b'{}'
    class Session:
        headers = {}
        def __init__(self): self.calls = 0
        def get(self, *args, **kwargs):
            self.calls += 1
            return Response()
    session = Session()
    client = HttpClient(max_requests=100, interval=0, session=session)
    class Provider:
        name = 'mediacloud'
        def page(self, payload):
            client.get('https://provider.example/fixture')
            return [], None, False
    with AgentStore(tmp_path / 'p.sqlite') as store:
        for i in range(3):
            store.enqueue('mediacloud', {'candidate_ids': [], 'query': f'fixture{i}',
                'start': '2026-09-01', 'end': '2026-09-30', 'domains': [], 'cursor': None})
        store.con.commit()
        result = SentimentWorkflow(store).run([], '2026-10-06', run_network=True,
            client_override=client, provider_override=Provider(), budget=RunBudget(max_requests=2))
        assert result['http_requests_used'] == 2 == session.calls
        assert store.rows("SELECT COUNT(*) n FROM cs_jobs WHERE status='pending'")[0]['n'] == 1
