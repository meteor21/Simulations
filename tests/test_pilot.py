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


def test_fec_failure_report_has_safe_actionable_diagnostics(tmp_path, monkeypatch):
    from charisma_lab.importers import FecAcquisitionError
    credential = 'nonsecret-test-fixture'
    monkeypatch.setenv('MEDIACLOUD_API_KEY', credential)
    def unavailable(*args, **kwargs):
        raise FecAcquisitionError('download', 'http_status', cycle=2026, http_status=404)
    monkeypatch.setattr('charisma_lab.pilot.download_fec_cycles', unavailable)
    report = run_pilot(tmp_path / 'out', run_network=True, download_fec=True)
    assert report['fec_error'] == {'stage': 'download', 'reason': 'http_status',
                                   'cycle': 2026, 'http_status': 404}
    assert report['status'] == 'blocked'
    assert report['selected_candidates'] == 0
    assert report['http_attempts_total'] == 0
    assert credential not in (tmp_path / 'out/pilot_report.json').read_text()
    assert 'FEC acquisition failed: download/http_status' in report['blockers']


def test_github_fec_failure_is_visible_in_annotations(tmp_path, monkeypatch, capsys):
    from charisma_lab.pilot import main
    monkeypatch.setenv('GITHUB_ACTIONS', 'true')
    monkeypatch.setattr('sys.argv', ['pilot', '--output', str(tmp_path)])
    monkeypatch.setattr('charisma_lab.pilot.run_pilot', lambda **kwargs: {
        'blockers': ['FEC unavailable'],
        'fec_error': {'stage': 'download', 'reason': 'http_status', 'http_status': 404}})
    assert main() == 2
    assert '::error title=FEC acquisition failed::' in capsys.readouterr().out


@pytest.mark.parametrize('status', [401, 403])
def test_http_access_denial_preserves_status_without_retrying(status):
    from charisma_lab.network import AccessBlocked
    class Session:
        headers = {}
        def get(self, *args, **kwargs):
            return SimpleNamespace(status_code=status, headers={}, close=lambda: None)
    client = HttpClient(session=Session(), interval=0)
    with pytest.raises(AccessBlocked) as error:
        client.get('https://provider.example/fixture')
    assert error.value.http_status == status
    assert error.value.reason == 'access_denied'
    assert client.requests_used == 1


@pytest.mark.parametrize('status', [401, 403])
def test_source_access_denial_prevents_candidate_collection(tmp_path, monkeypatch, status):
    from charisma_lab.agents import SentimentWorkflow
    monkeypatch.setenv('MEDIACLOUD_API_KEY', 'nonsecret-test-fixture')
    monkeypatch.setattr('charisma_lab.agents_sources.SourceAgent.resolve', lambda *args, **kwargs: [
        {'domain': 'news.example', 'status': 'error', 'error_type': 'AccessBlocked', 'http_status': status}])
    monkeypatch.setattr(SentimentWorkflow, 'run', lambda *args, **kwargs: pytest.fail('Access denial must stop collection'))
    output = tmp_path / 'out'
    output.mkdir()
    with AgentStore(output / 'pilot.sqlite') as store:
        seed(store)
    report = run_pilot(output, run_network=True)
    assert report['status'] == 'blocked'
    assert report['selected_candidates'] == 24
    assert report['http_attempts_total'] == 0
    assert any(f'HTTP {status}' in blocker for blocker in report['blockers'])


def test_checkpoint_analysis_preserves_counter_and_missing_sentiment_without_network(tmp_path, monkeypatch):
    monkeypatch.setattr(HttpClient, 'get', lambda *args, **kwargs: pytest.fail('Checkpoint analysis must make no provider calls'))
    output = tmp_path / 'out'
    output.mkdir()
    with AgentStore(output / 'pilot.sqlite') as store:
        seed(store)
    run_pilot(output)  # Initialize the original pilot policy without network calls.
    with AgentStore(output / 'pilot.sqlite') as store:
        ledger = RequestLedger(store, policy={'cycle': 2026, 'start': '2026-09-01', 'as_of': '2026-10-06',
            'provider': 'mediacloud', 'candidate_limit': 24, 'roster_only': False})
        for _ in range(3): ledger.reserve()
        store.article(url='https://fixture.example/campaign', title='Fixture Person0 campaign',
                      candidate_ids=['SYNTHETIC_0'], published_at='2026-09-01', retrieved_at='2026-09-02')
        store.con.commit()
    report = run_pilot(output, analyze_existing=True)
    assert report['status'] == 'analyzed_partial'
    assert report['analysis_only'] is True
    assert report['selected_candidates'] == len(report['run']['features']) == 24
    assert report['http_attempts_before'] == report['http_attempts_total'] == 3
    assert report['provider_attempts_sent_this_run'] == report['http_attempts_this_run'] == 0
    assert report['observations']['unique_article_urls'] == 1
    assert all(r['media_recency_score'] is None for r in report['run']['features'])
    assert (output / 'exports/candidate_sentiment_summary.csv').is_file()


def test_checkpoint_analysis_cannot_create_a_new_database_or_quota(tmp_path):
    output = tmp_path / 'missing'
    with pytest.raises(ValueError, match='already initialized'):
        run_pilot(output, analyze_existing=True)
    assert not output.exists()


def test_checkpoint_analysis_refuses_a_database_without_the_original_ledger(tmp_path):
    output = tmp_path / 'out'
    output.mkdir()
    with AgentStore(output / 'pilot.sqlite') as store:
        seed(store)
    with pytest.raises(ValueError, match='original pilot request ledger'):
        run_pilot(output, analyze_existing=True)
    with AgentStore(output / 'pilot.sqlite') as store:
        assert not store.rows("SELECT 1 FROM cs_meta WHERE key='pilot_request_policy'")


@pytest.mark.parametrize('options', [{'run_network': True}, {'download_fec': True}, {'fec_zip': 'new-input.zip'}])
def test_checkpoint_analysis_cannot_enable_collection_or_new_imports(tmp_path, options):
    with pytest.raises(ValueError, match='cannot collect or import'):
        run_pilot(tmp_path, analyze_existing=True, **options)


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
