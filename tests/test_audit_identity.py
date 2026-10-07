"""Regression cases discovered by the v0.2 identity/provenance audit."""
import csv
import json

import pytest

from charisma_lab.agents_sources import import_terms
from charisma_lab.agents_store import AgentStore
from charisma_lab.importers import import_aliases, import_annotations
from charisma_lab.util import digest, iso


@pytest.fixture
def audit_store(tmp_path):
    with AgentStore(tmp_path / 'audit.sqlite') as store:
        store.candidate('C1', 'Alex Rowan', ['Alexandra Rowan'],
                        known_at='2020-01-01', source_url='synthetic://identity')
        yield store


def write_csv(path, row):
    with path.open('w', newline='') as out:
        writer = csv.DictWriter(out, fieldnames=list(row))
        writer.writeheader()
        writer.writerow(row)
    return path


def test_identity_crosswalk_rejects_registry_conflict(audit_store):
    audit_store.con.execute("UPDATE cs_candidates SET person_id='person:one' WHERE candidate_id='C1'")
    with pytest.raises(ValueError, match='Identity conflict'):
        audit_store.identity_link('C1', 'person:two', 'synthetic://conflict')
    assert audit_store.rows('SELECT * FROM sa_identity_links') == []


@pytest.mark.parametrize('identity_table', ['cs_candidates', 'sa_identity_links'])
def test_alias_import_cannot_reassign_person(audit_store, tmp_path, identity_table):
    if identity_table == 'cs_candidates':
        audit_store.con.execute("UPDATE cs_candidates SET person_id='person:one' WHERE candidate_id='C1'")
    else:
        audit_store.identity_link('C1', 'person:one', 'synthetic://link')
    path = write_csv(tmp_path / 'aliases.csv', dict(candidate_id='C1', aliases_json='["Alexandra Rowan"]',
                     person_id='person:two', source_url='synthetic://conflict'))
    with pytest.raises(ValueError, match='Identity conflict'):
        import_aliases(audit_store, path)
    assert audit_store.rows('SELECT person_id FROM cs_candidates')[0]['person_id'] != 'person:two'


def test_alias_import_retains_previously_documented_names(audit_store, tmp_path):
    path = write_csv(tmp_path / 'aliases.csv', dict(candidate_id='C1', aliases_json='["Alex J. Rowan"]',
                     source_url='synthetic://additional-name'))
    import_aliases(audit_store, path)
    aliases = json.loads(audit_store.rows('SELECT aliases_json FROM cs_candidates')[0]['aliases_json'])
    assert aliases == ['Alex Rowan', 'Alexandra Rowan', 'Alex J. Rowan']


def test_service_csv_uses_midnight_exclusive_boundaries(audit_store, tmp_path):
    path = write_csv(tmp_path / 'terms.csv', dict(person_id='person:one', candidate_id='C1', office='H',
          state='MI', start_date='2025-01-03', end_date='2027-01-03', available_at='2025-01-03',
          evidence_url='synthetic://service'))
    import_terms(audit_store, path)
    term = audit_store.rows('SELECT * FROM sa_service_terms')[0]
    assert term['start_date'] == '2025-01-03T00:00:00+00:00'
    assert term['end_date'] == '2027-01-03T00:00:00+00:00'
    assert term['available_at'] == '2025-01-03T23:59:59+00:00'


def test_source_profile_observation_provenance_retained(audit_store):
    profile = dict(domain='example.org', name='Example', scope='local', states=['MI'],
                   valid_from='2020-01-01', evidence_url='synthetic://directory')
    first = audit_store.source_profile(**profile, observed_at='2020-01-02', geography={'city': 'One'})
    second = audit_store.source_profile(**profile, observed_at='2020-02-02', geography={'city': 'Two'})
    assert first != second
    assert len(audit_store.rows('SELECT * FROM sa_source_profiles')) == 2
    assert audit_store.profile_for('https://example.org/story', '2020-06-01', '2020-06-02')['profile_id'] == second
    assert audit_store.profile_for('https://example.org/story', '2020-01-03', '2020-01-04')['profile_id'] == first


def test_edition_prefix_is_a_path_component(audit_store):
    audit_store.source_profile(domain='example.org', name='Michigan', scope='local', states=['MI'],
        url_prefix='https://example.org/local/mi', observed_at='2020-01-01', evidence_url='synthetic://scope')
    assert audit_store.profile_for('https://example.org/local/miami/story', '2021-01-01', '2021-01-02') is None
    assert audit_store.profile_for('https://example.org/local/mi/story', '2021-01-01', '2021-01-02')['scope'] == 'local'


def add_rating(store, **extra):
    fields = dict(domain='example.org', provider='TestProvider', label='Left',
                  valid_from='2020-01-01', available_at='2020-01-02', evidence_url='synthetic://rating')
    fields.update(extra)
    return store.bias(**fields)


def test_rating_provenance_is_not_silently_dropped(audit_store):
    first = add_rating(audit_store, evidence_url='synthetic://rating/one', native_score=-3,
                       native_scale='provider-native', license_note='attribution required')
    second = add_rating(audit_store, evidence_url='synthetic://rating/two', native_score=-4,
                        native_scale='provider-native', license_note='research only')
    assert first != second
    rating = audit_store.rating_for('example.org', '2021-01-01', '2021-01-02')
    assert {r['evidence_url'] for r in rating['assessments']} == {'synthetic://rating/one', 'synthetic://rating/two'}
    assert {r['native_score'] for r in rating['assessments']} == {-3, -4}


def test_tied_provider_disagreement_is_explicit(audit_store):
    add_rating(audit_store, label='Left')
    add_rating(audit_store, label='Right')
    rating = audit_store.rating_for('example.org', '2021-01-01', '2021-01-02')
    assert rating['label'] == 'Mixed/Disputed'
    assert rating['ordinal_index'] is None
    assert len(rating['assessments']) == 2


def test_genre_specific_rating_precedes_all_genres_fallback(audit_store):
    add_rating(audit_store, label='Left', genre='all')
    add_rating(audit_store, label='Right', genre='opinion')
    assert audit_store.rating_for('example.org', '2021-01-01', '2021-01-02', genre='opinion')['label'] == 'Right'
    assert audit_store.rating_for('example.org', '2021-01-01', '2021-01-02', genre='online_news')['label'] == 'Left'


def test_rating_domain_normalization_preserves_lookup(audit_store):
    add_rating(audit_store, domain='WWW.EXAMPLE.ORG')
    assert audit_store.rating_for('example.org', '2021-01-01', '2021-01-02')['label'] == 'Left'


def test_annotation_csv_preserves_dated_review_evidence(audit_store, tmp_path):
    version = audit_store.article(url='https://example.org/story', title='Alex Rowan campaign',
                    candidate_ids=['C1'], published_at='2020-01-01', retrieved_at='2020-01-02')
    path = write_csv(tmp_path / 'annotations.csv', dict(version_id=version, candidate_id='C1',
          sentiment='.5', evidence='Alex Rowan campaign', reviewed='1', annotated_at='2020-01-03',
          annotation_basis='verified_annotation_record', annotation_evidence_url='synthetic://dated-review'))
    import_annotations(audit_store, path)
    annotation = audit_store.rows('SELECT * FROM cs_annotations')[0]
    assert annotation['annotated_at'] == '2020-01-03T23:59:59+00:00'
    diagnostics = json.loads(annotation['diagnostics_json'])
    assert diagnostics['annotation_basis'] == 'verified_annotation_record'
    assert diagnostics['annotation_evidence_url'] == 'synthetic://dated-review'


def test_annotation_csv_cannot_silently_backdate_review(audit_store, tmp_path):
    version = audit_store.article(url='https://example.org/story', title='Alex Rowan campaign',
                    candidate_ids=['C1'], published_at='2020-01-01', retrieved_at='2020-01-02')
    path = write_csv(tmp_path / 'annotations.csv', dict(version_id=version, candidate_id='C1',
          sentiment='.5', evidence='Alex Rowan campaign', reviewed='1', annotated_at='2020-01-03'))
    with pytest.raises(ValueError):
        import_annotations(audit_store, path)


def test_existing_v02_profile_reimport_keeps_id_and_count(audit_store):
    fields = dict(domain='example.org', name='Example', scope='state', states=['MI'],
                  observed_at='2020-01-02', valid_from='2020-01-01', evidence_url='synthetic://scope')
    current = audit_store.source_profile(**fields)
    original = digest(['example.org', '', iso('2020-01-01'), 'state', ['MI'], 'synthetic://scope'])
    audit_store.con.execute('UPDATE sa_source_profiles SET profile_id=? WHERE profile_id=?', (original, current))
    assert audit_store.source_profile(**fields) == original
    assert len(audit_store.rows('SELECT * FROM sa_source_profiles')) == 1
    # An actual new observation still receives its own retained provenance.
    assert audit_store.source_profile(**dict(fields, observed_at='2020-02-02')) != original
    assert len(audit_store.rows('SELECT * FROM sa_source_profiles')) == 2


def test_existing_v02_bias_reimport_keeps_id_and_count(audit_store):
    current = add_rating(audit_store)
    original = digest(['example.org', 'TestProvider', iso('2020-01-01'), None, iso('2020-01-02'),
                       'online_news', 'sourced_provider_rating', 'Left', {}])
    audit_store.con.execute('UPDATE sa_bias_assessments SET assessment_id=? WHERE assessment_id=?', (original, current))
    assert add_rating(audit_store) == original
    assert len(audit_store.rows('SELECT * FROM sa_bias_assessments')) == 1
    assert add_rating(audit_store, evidence_url='synthetic://additional-evidence') != original
    assert len(audit_store.rows('SELECT * FROM sa_bias_assessments')) == 2
