"""Public metadata allowlist and saved-checkpoint dashboard tests (synthetic)."""
import csv
import hashlib
import json
import socket

import pytest

from charisma_lab.agents_store import AgentStore
from charisma_lab.dashboard_data import build_dashboard_data
from charisma_lab.pilot import RequestLedger
from charisma_lab.util import iso


@pytest.fixture
def checkpoint(tmp_path):
    folder = tmp_path / 'analyzed-pilot'
    folder.mkdir()
    policy = {'cycle': 2026, 'start': '2026-09-01', 'as_of': '2026-10-06',
              'provider': 'mediacloud', 'candidate_limit': 24, 'roster_only': False}
    with AgentStore(folder / 'pilot.sqlite') as store:
        RequestLedger(store, policy=policy)
        store.con.execute("UPDATE cs_meta SET value='16' WHERE key='pilot_requests_used'")
        for cid in ('C1', 'C2', 'UNSELECTED'):
            store.candidate(cid, 'Alex ' + cid, known_at='2026-01-01', source_url='https://www.fec.gov/records/')
        for domain, scope, states in [('national.example.org', 'national', []),
                                      ('local.example.org', 'local', ['MI'])]:
            store.source_profile(domain=domain, name='Synthetic source', scope=scope, states=states,
                                 observed_at='2026-10-06', evidence_url='https://statesnewsroom.com/newsrooms/?token=HIDDEN')
        version = store.article(url='https://national.example.org/story?api_key=SECRET_QUERY#PRIVATE_FRAGMENT',
            title='PRIVATE_ARTICLE_TITLE', body='PRIVATE_ARTICLE_BODY' * 20, candidate_ids=['C1', 'UNSELECTED'],
            published_at='2026-09-15', retrieved_at='2026-10-07', metadata={'secret': 'PRIVATE_METADATA'})
        store.article(url='https://local.example.org/only-unselected', title='UNSELECTED_PRIVATE_TITLE',
            candidate_ids=['UNSELECTED'], published_at='2026-09-16', retrieved_at='2026-10-07')
        store.article(url='https://national.example.org/future', title='FUTURE_PRIVATE_TITLE',
            candidate_ids=['C1'], published_at='2026-10-07', retrieved_at='2026-10-07')
        store.article(url='https://national.example.org/too-old', title='OLD_PRIVATE_TITLE',
            candidate_ids=['C1'], published_at='2026-08-31', retrieved_at='2026-10-07')
        store.con.commit()
    columns = ['candidate_id', 'name', 'cycle', 'office', 'state', 'district', 'party',
               'roster_status', 'known_at', 'source_url']
    with (folder / 'selected_congressional_cohort.csv').open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        for cid in ('C2', 'C1'):
            writer.writerow(dict(candidate_id=cid, name='Alex ' + cid, cycle=2026, office='H', state='MI',
                district='1', party='X', roster_status='registry_only', known_at='2026-01-01',
                source_url='https://www.fec.gov/records/?access_token=PRIVATE_ROSTER_QUERY'))
    original = {'status': 'blocked', 'http_attempts_total': 16,
        'blockers': ['Source panel incomplete; inspect source_resolution and collection_plan'],
        'source_resolution': [{'domain': 'national.example.org', 'status': 'exact_root_homepage_match',
                               'source_id': 123, 'raw_response': 'PRIVATE_PROVIDER_RESPONSE'},
                              {'domain': 'local.example.org', 'status': 'not_found'}],
        'run': {'collection': {'processed': 6, 'processed_hits': 4, 'blocked': 0, 'errors': 0}}}
    feature = {'candidate_id': 'C1', 'as_of': '2026-10-06', 'mode': 'retrospective', 'reviewed_only': True,
               'state': 'MI', 'cycle': 2026,
               'media_recency_score': None, 'national': {'score': None}, 'subnational': {'score': None},
               'raw_review': 'PRIVATE_REVIEW_EVIDENCE'}
    report = {'source_repository': 'example/repository', 'source_run_id': 1234,
              'collection_source_commit': 'abc123', 'analysis_only': True, 'provider_requests_made': 0,
              'original_pilot_report': original,
              'analysis': {'status': 'analyzed_partial', 'http_attempts_total': 16,
                           'warnings': ['No reviewed candidate-specific sentiment annotations; scores remain missing'],
                           'run': {'features': [feature]}}}
    (folder / 'analysis_report.json').write_text(json.dumps(report))
    return folder, version, report


def build(folder):
    return build_dashboard_data(folder, source_repository='example/repository',
                                analysis_run_id=5678, code_revision='def456')


def save_report(folder, report):
    (folder / 'analysis_report.json').write_text(json.dumps(report))


def save_snapshot(folder, feature, lookback=731):
    with AgentStore(folder / 'pilot.sqlite') as store:
        store.con.execute('INSERT INTO sa_snapshots VALUES(?,?,?,?,?,?,?,?)', (
            'synthetic-snapshot-' + str(lookback), feature['candidate_id'], feature['cycle'], iso(feature['as_of']),
            feature['mode'], json.dumps({'lookback_days': lookback, 'mode': feature['mode'], 'reviewed_only': True}),
            json.dumps(feature), '2026-10-07T00:00:00+00:00'))
        store.con.commit()


def test_public_export_is_selected_cohort_metadata_only(checkpoint):
    folder, _, _ = checkpoint
    data = build(folder)
    text = json.dumps(data)
    for private in ('PRIVATE', 'SECRET_QUERY', 'UNSELECTED', 'api_key', 'access_token', 'raw_response',
                    'title', 'body_z', 'diagnostics_json', 'credential_present'):
        assert private not in text
    assert [c['candidate_id'] for c in data['candidates']] == ['C1', 'C2']
    assert data['summary']['article_urls'] == 1
    assert data['checkpoint_counts']['article_urls'] == 4
    assert data['articles'][0]['url'] == 'https://national.example.org/story'
    assert data['articles'][0]['candidate_ids'] == ['C1']
    assert data['articles'][0]['association_status'] == 'unreviewed_search_association'
    assert data['articles'][0]['historical_scope_verified'] is False
    assert data['summary']['retrospective_scope_urls'] == 1
    assert all(c['roster_status'] == 'registry_only' for c in data['candidates'])
    assert data['collection'] == {'processed_jobs': 6, 'processed_hits': 4, 'blocked_jobs': 0, 'failed_jobs': 0}


def test_missing_labels_remain_null_with_explicit_coverage(checkpoint):
    folder, _, _ = checkpoint
    data = build(folder)
    assert data['summary']['candidates_with_scores'] == 0
    assert data['summary']['reviewed_annotations'] == 0
    assert data['coverage'] == {'national': 1, 'state': 0, 'metro': 0, 'local': 0, 'unknown': 0}
    for candidate in data['candidates']:
        assert all(value is None for value in candidate['features'].values())
        assert 'no_reviewed_candidate_sentiment' in candidate['missingness']
    assert data['window'] == {'start': '2026-09-01', 'as_of': '2026-10-06', 'cycle': 2026, 'mode': 'retrospective'}
    assert data['budget'] == {'limit': 20, 'used': 16, 'remaining': 4, 'provider_requests_this_analysis': 0}


def test_original_completeness_and_geography_evidence_preserved(checkpoint):
    folder, _, _ = checkpoint
    with AgentStore(folder / 'pilot.sqlite') as store:
        store.con.execute("UPDATE sa_source_profiles SET geography_json=? WHERE scope='local'",
                          (json.dumps({'metro': 'Detroit', 'district_mapping_verified': False,
                                       'raw_response': 'PRIVATE_GEOGRAPHY_METADATA'}),))
        store.con.commit()
    data = build(folder)
    assert data['original_status'] == 'blocked'
    assert data['current_status'] == 'analyzed_partial'
    assert data['warnings']['original'] == ['Source panel incomplete; inspect source_resolution and collection_plan']
    local = next(source for source in data['sources'] if source['scope'] == 'local')
    assert local['resolution_status'] == 'not_found'
    assert local['states'] == ['MI']
    assert local['geography'] == {'metro': 'Detroit', 'district_mapping_verified': False}
    assert local['observed_at'].startswith('2026-10-06')
    assert local['evidence_url'] == 'https://statesnewsroom.com/newsrooms/'


def test_zero_score_preserved_only_with_reviewed_labels_at_matching_cutoff(checkpoint):
    folder, version, report = checkpoint
    with AgentStore(folder / 'pilot.sqlite') as store:
        store.annotation(version, 'C1', -1, reviewed=True, evidence='PRIVATE_REVIEW_EVIDENCE')
        store.con.commit()
    feature = report['analysis']['run']['features'][0]
    feature['media_recency_score'] = feature['national']['score'] = 0
    save_report(folder, report)
    save_snapshot(folder, feature)
    candidate = build(folder)['candidates'][0]
    assert candidate['features']['media_recency_score'] == 0
    assert candidate['reviewed_annotations'] == 1
    assert candidate['feature_provenance']['lookback_days'] == 731
    assert candidate['feature_provenance']['lookback_start'] == '2024-10-05T23:59:59+00:00'
    assert candidate['feature_provenance']['same_as_metadata_window'] is False
    feature['as_of'] = '2026-11-04'
    save_report(folder, report)
    candidate = build(folder)['candidates'][0]
    assert candidate['features']['media_recency_score'] is None
    assert 'no_matching_reviewed_snapshot' in candidate['missingness']


def test_malformed_feature_and_warning_cannot_publish_secret(checkpoint):
    folder, _, report = checkpoint
    report['analysis']['warnings'].append('Provider key: VERY_PRIVATE_TOKEN')
    report['analysis']['run']['features'][0]['media_recency_score'] = 50
    save_report(folder, report)
    data = build(folder)
    assert 'VERY_PRIVATE_TOKEN' not in json.dumps(data)
    assert 'Additional diagnostic withheld from public export' in data['warnings']['current']
    assert data['candidates'][0]['features']['media_recency_score'] is None


@pytest.mark.parametrize('url', ['http://127.0.0.1/private', 'http://localhost/private',
    'https://national.example.org:444/private', 'https://unapproved.example.net/private',
    'https://user:PRIVATE_PASSWORD@national.example.org/private', 'file:///tmp/private'])
def test_unsafe_or_unapproved_article_urls_never_published(checkpoint, url):
    folder, _, _ = checkpoint
    with AgentStore(folder / 'pilot.sqlite') as store:
        store.con.execute('UPDATE cs_articles SET url=? WHERE url LIKE ?', (url, '%story%'))
        store.con.commit()
    assert build(folder)['articles'] == []


def test_builder_is_deterministic_read_only_and_offline(checkpoint, monkeypatch):
    folder, _, _ = checkpoint
    before = hashlib.sha256((folder / 'pilot.sqlite').read_bytes()).hexdigest()
    def prohibited(*args, **kwargs):
        raise AssertionError('A public projection must not initialize a writable store or use the network')
    monkeypatch.setattr(AgentStore, '__init__', prohibited)
    monkeypatch.setattr(socket, 'create_connection', prohibited)
    first = build(folder)
    second = build(folder)
    assert json.dumps(first, sort_keys=True, allow_nan=False) == json.dumps(second, sort_keys=True, allow_nan=False)
    assert hashlib.sha256((folder / 'pilot.sqlite').read_bytes()).hexdigest() == before


def test_request_count_uses_highest_original_remote_and_checkpoint_values(checkpoint):
    folder, _, report = checkpoint
    report['original_pilot_report']['github_requests_reserved'] = 18
    save_report(folder, report)
    assert build(folder)['budget']['used'] == 18
    report['original_pilot_report']['github_requests_reserved'] = 21
    save_report(folder, report)
    with pytest.raises(ValueError, match='accounting'):
        build(folder)


def test_source_repository_cannot_be_substituted(checkpoint):
    folder, _, _ = checkpoint
    with pytest.raises(ValueError, match='repository does not match'):
        build_dashboard_data(folder, source_repository='other/repository', analysis_run_id=5678, code_revision='abc')


def test_reviewed_older_version_count_is_retained_when_latest_version_unreviewed(checkpoint):
    folder, version, _ = checkpoint
    with AgentStore(folder / 'pilot.sqlite') as store:
        store.annotation(version, 'C1', .5, reviewed=True, evidence='PRIVATE_REVIEW_EVIDENCE')
        store.article(url='https://national.example.org/story?api_key=SECRET_QUERY#PRIVATE_FRAGMENT',
            title='PRIVATE_UPDATED_TITLE', candidate_ids=['C1'], published_at='2026-09-15', retrieved_at='2026-10-08')
        store.con.commit()
    data = build(folder)
    assert data['summary']['article_urls'] == 1
    assert data['summary']['reviewed_annotations'] == 1
    assert data['candidates'][0]['reviewed_annotations'] == 1


def test_election_id_without_explicit_membership_does_not_verify_contest(checkpoint):
    folder, _, _ = checkpoint
    path = folder / 'selected_congressional_cohort.csv'
    with path.open(newline='') as stream:
        rows = list(csv.DictReader(stream))
    for row in rows:
        row['election_id'] = 'claimed-general-election'
        row['roster_status'] = ''
    with path.open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    assert {c['roster_status'] for c in build(folder)['candidates']} == {'registry_only'}


@pytest.mark.parametrize('field,value', [('state', 'PA'), ('cycle', 2024)])
def test_snapshot_for_different_state_or_cycle_cannot_supply_scores(checkpoint, field, value):
    folder, version, report = checkpoint
    with AgentStore(folder / 'pilot.sqlite') as store:
        store.annotation(version, 'C1', .5, reviewed=True, evidence='PRIVATE_REVIEW_EVIDENCE')
        store.con.commit()
    feature = report['analysis']['run']['features'][0]
    feature['media_recency_score'] = 75
    feature[field] = value
    save_report(folder, report)
    save_snapshot(folder, feature)
    candidate = build(folder)['candidates'][0]
    assert candidate['features']['media_recency_score'] is None
    assert candidate['feature_provenance'] is None
    assert 'no_matching_reviewed_snapshot' in candidate['missingness']


def test_nonnull_feature_without_persisted_lookback_is_withheld(checkpoint):
    folder, version, report = checkpoint
    with AgentStore(folder / 'pilot.sqlite') as store:
        store.annotation(version, 'C1', .5, reviewed=True, evidence='PRIVATE_REVIEW_EVIDENCE')
        store.con.commit()
    report['analysis']['run']['features'][0]['media_recency_score'] = 75
    save_report(folder, report)
    candidate = build(folder)['candidates'][0]
    assert candidate['features']['media_recency_score'] is None
    assert 'feature_lookback_provenance_unavailable' in candidate['missingness']
