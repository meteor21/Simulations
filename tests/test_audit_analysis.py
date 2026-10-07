"""Regression cases established by the v0.2 takeover audit; no live services."""
import pandas as pd
import pytest

from charisma_lab.agents_analysis import FeatureConfig, snapshot
from charisma_lab.agents_store import AgentStore
from charisma_lab.annotate import target_context
from charisma_lab.evaluate import walk_forward
from charisma_lab.scoring import ScoreConfig, score_candidate


@pytest.fixture
def audit_db(tmp_path):
    with AgentStore(tmp_path / 'analysis.sqlite') as db:
        db.candidate('C1', 'Alex Rowan', known_at='1990-01-01', source_url='synthetic://candidate')
        for domain, scope, states in [('national.example', 'national', []), ('local.example', 'local', ['MI'])]:
            db.source_profile(domain=domain, name=domain, scope=scope, states=states,
                              observed_at='1990-01-01', valid_from='1990-01-01', evidence_url='synthetic://source')
        yield db


def add_article(db, domain, slug, published='2026-09-20', body=''):
    title = f'Congress candidate Alex Rowan {slug}'
    version = db.article(url=f'https://{domain}/{slug}', title=title, body=body,
                         candidate_ids=['C1'], published_at=published, retrieved_at=published)
    db.annotation(version, 'C1', .6, evidence=title,annotated_at=published,
                  annotation_basis='synthetic_fixture',annotation_evidence_url='synthetic://article-label-fixture')
    db.con.commit()
    return version


def config(**kw):
    return FeatureConfig(min_outlets=1, min_unique_articles=1, **kw)


def test_masking_preserves_other_person_with_same_surname():
    text = 'Senator Alex Rowan was praised. Rival Sam Rowan was condemned.'
    contexts, evidence = target_context(text, ['Alex Rowan'])
    assert 'TARGET_CANDIDATE was praised' in contexts[0]
    assert 'Sam Rowan was condemned' in contexts[0]
    assert 'Sam TARGET_CANDIDATE' not in contexts[0]
    assert evidence == text


@pytest.mark.parametrize('aliases', [[], [''], ['!!!']])
def test_empty_or_punctuation_alias_never_matches_every_position(aliases):
    assert target_context('An unrelated article about a candidate.', aliases) == ([], '')


def test_strict_unknown_identity_does_not_emit_component_features(audit_db):
    add_article(audit_db, 'national.example', 'n')
    add_article(audit_db, 'local.example', 'l')
    audit_db.con.execute("UPDATE cs_candidates SET known_at='2027-01-01T00:00:00+00:00'")
    result = snapshot(audit_db, 'C1', '2026-10-06', state='MI', config=config())
    assert result['national']['score'] is None
    assert result['national']['descriptive_score'] is None
    assert result['subnational']['score'] is None
    assert result['scope_detail']['local']['score'] is None
    assert result['media_recency_score'] is None
    assert 'candidate_identity_not_known_by_cutoff' in result['flags']
    retro = snapshot(audit_db, 'C1', '2026-10-06', state='MI', config=config(mode='retrospective'))
    assert retro['media_recency_score'] == 80


def test_strict_state_inference_ignores_later_cycle_registration(audit_db):
    audit_db.con.execute('INSERT INTO cs_candidate_cycles VALUES(?,?,?,?,?,?,?,?,?,?)',
                         ('C1', 2026, 'H', 'MI', '1', 'X', 2026, 'registry_only',
                          '2027-01-01T00:00:00+00:00', 'synthetic://late-registry'))
    add_article(audit_db, 'local.example', 'l')
    result = snapshot(audit_db, 'C1', '2026-10-06', cycle=2026, config=config())
    assert result['state'] is None
    assert result['subnational']['score'] is None


def test_legacy_strict_score_also_hides_preidentity_components(audit_db):
    add_article(audit_db, 'national.example', 'n')
    audit_db.con.execute("UPDATE cs_candidates SET known_at='2027-01-01T00:00:00+00:00'")
    cfg = ScoreConfig(min_news_articles=1, min_news_outlets=1)
    result = score_candidate(audit_db, 'C1', '2026-10-06', geography='US', population='rv', config=cfg)
    assert result['recency_score'] is None
    assert result['recency']['raw_diagnostic_score'] is None
    assert result['recency']['unique_articles'] == 0
    assert result['pedigree']['flags'] == ['candidate_registry_not_verified_asof']
    retro = score_candidate(audit_db, 'C1', '2026-10-06', geography='US', population='rv', config=cfg, mode='research')
    assert retro['recency_score'] == 80


def test_republished_duplicate_cannot_satisfy_recent_coverage(audit_db):
    body = 'Senator Alex Rowan discussed the campaign. ' * 20
    add_article(audit_db, 'national.example', 'old', published='2026-01-01', body=body)
    add_article(audit_db, 'national.example', 'copy-one', body=body)
    add_article(audit_db, 'national.example', 'copy-two', body=body)
    result = snapshot(audit_db, 'C1', '2026-10-06', state='MI',
                      config=config(require_both_scopes=False, min_recent_articles=2))
    assert result['national']['unique_text_clusters'] == 1
    assert result['media_recency_score'] is None
    assert 'recent_coverage_stale' in result['flags']


def test_negative_recent_coverage_requirement_rejected():
    with pytest.raises(ValueError, match='min_recent_articles'):
        config(min_recent_articles=-1)


def frame():
    return pd.DataFrame([
        dict(election_id=f'{year}-{i}', cycle=year, as_of=f'{year}-10-01',
             election_date=f'{year}-11-01', won=i % 2, baseline=i / 10, standing=i / 20)
        for year in [2020, 2022, 2024] for i in range(4)
    ])


@pytest.mark.parametrize('column', ['as_of', 'election_date', 'cycle', 'election_id'])
def test_backtest_missing_temporal_or_race_identity_rejected(column):
    data = frame()
    data.loc[0, column] = None
    with pytest.raises(ValueError, match='missing|Missing'):
        walk_forward(data, ['baseline'], ['standing'])


def test_backtest_future_training_outcome_rejected():
    data = frame()
    data.loc[0, 'election_date'] = '2023-01-01'
    with pytest.raises(ValueError, match='outcome|Outcome'):
        walk_forward(data, ['baseline'], ['standing'])


def test_backtest_target_cannot_be_used_as_a_feature():
    with pytest.raises(ValueError, match='feature|Feature'):
        walk_forward(frame(), ['won'], ['standing'])


def test_backtest_dated_outcome_release_after_snapshot_rejected():
    data = frame()
    data['outcome_available_at'] = data['election_date']
    data.loc[0, 'outcome_available_at'] = '2023-01-01'
    with pytest.raises(ValueError, match='outcome|Outcome'):
        walk_forward(data, ['baseline'], ['standing'])


@pytest.mark.parametrize('reviewed,model_id', [(True, 'human:late-review'), (False, 'model:late-inference')])
def test_postcutoff_annotations_excluded_in_strict_but_flagged_in_reconstruction(audit_db, reviewed, model_id):
    version = add_article(audit_db, 'national.example', 'n')
    audit_db.con.execute('DELETE FROM cs_annotations WHERE version_id=?', (version,))
    audit_db.annotation(version, 'C1', -.8, model_id=model_id, reviewed=reviewed,
                        evidence='Congress candidate Alex Rowan n', annotated_at='2026-11-04',
                        annotation_basis='synthetic_fixture', annotation_evidence_url='synthetic://post-election-label')
    strict = snapshot(audit_db, 'C1', '2026-10-06', state='MI',
                      config=config(reviewed_only=reviewed, require_both_scopes=False))
    assert strict['national']['article_urls'] == 0
    assert strict['national']['score'] is None
    assert strict['media_recency_score'] is None
    retro = snapshot(audit_db, 'C1', '2026-10-06', state='MI',
                     config=config(mode='retrospective', reviewed_only=reviewed, require_both_scopes=False))
    assert retro['national']['score'] == pytest.approx(10)
    assert retro['national']['retrospectively_annotated_articles'] == 1
    assert 'later_annotations_present' in retro['flags']
    cfg = ScoreConfig(min_news_articles=1, min_news_outlets=1, require_reviewed=reviewed)
    legacy = score_candidate(audit_db, 'C1', '2026-10-06', geography='US', population='rv', config=cfg)
    assert legacy['recency_score'] is None
    assert legacy['recency']['exclusions']['annotation_not_available_by_cutoff'] == 1
    legacy_retro = score_candidate(audit_db, 'C1', '2026-10-06', geography='US', population='rv', config=cfg, mode='research')
    assert legacy_retro['recency_score'] == pytest.approx(10)
    assert 'later_annotations_present' in legacy_retro['flags']


def test_earlier_annotation_survives_later_model_selection(audit_db):
    version = add_article(audit_db, 'national.example', 'n')
    audit_db.annotation(version, 'C1', -.8, model_id='human:later-rubric', reviewed=True,
                        evidence='Congress candidate Alex Rowan n', annotated_at='2026-11-04',
                        annotation_basis='synthetic_fixture', annotation_evidence_url='synthetic://later-label')
    result = snapshot(audit_db, 'C1', '2026-10-06', state='MI', config=config(require_both_scopes=False))
    assert result['national']['score'] == 80
    assert result['national']['article_urls'] == 1
    cfg = ScoreConfig(min_news_articles=1, min_news_outlets=1)
    legacy = score_candidate(audit_db, 'C1', '2026-10-06', geography='US', population='rv', config=cfg)
    assert legacy['recency_score'] == 80
    assert legacy['recency']['model_ids'] == ['human:v1']


def test_date_only_annotation_availability_is_end_of_day(audit_db):
    version = add_article(audit_db, 'national.example', 'n')
    audit_db.con.execute('DELETE FROM cs_annotations WHERE version_id=?', (version,))
    audit_db.annotation(version, 'C1', .6, evidence='Congress candidate Alex Rowan n',
                        annotated_at='2026-10-06', annotation_basis='synthetic_fixture',
                        annotation_evidence_url='synthetic://dated-label')
    midday = snapshot(audit_db, 'C1', '2026-10-06T12:00:00Z', state='MI', config=config())
    end_of_day = snapshot(audit_db, 'C1', '2026-10-06', state='MI', config=config())
    assert midday['national']['score'] is None
    assert end_of_day['national']['score'] == 80
