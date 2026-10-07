import io
import json
import zipfile
import pytest
from charisma_lab.transfer import create_bundle, read_bundle


def fixture_bundle(tmp_path):
    folder = tmp_path / 'exports'
    folder.mkdir()
    (folder / 'candidate_sentiment_summary.csv').write_text('candidate_id,media_recency_score\nSYNTHETIC_1,\n')
    (folder / 'private.sqlite').write_bytes(b'not for export')
    (folder / '.env').write_text('fixture secret excluded')
    (folder / 'annotation_review.json').write_text('private review text excluded')
    bundle = tmp_path / 'results.zip'
    create_bundle({'agents': folder}, bundle, dataset_kind='synthetic', source_commit='fixture-commit')
    return bundle


def test_only_permitted_exports_roundtrip_with_missing_preserved(tmp_path):
    manifest, files = read_bundle(fixture_bundle(tmp_path))
    assert manifest['dataset_kind'] == 'synthetic'
    assert manifest['source_commit'] == 'fixture-commit'
    assert list(files) == ['agents/candidate_sentiment_summary.csv']
    assert files['agents/candidate_sentiment_summary.csv'].endswith(b'SYNTHETIC_1,\n')


def test_github_artifact_wrapper_supported(tmp_path):
    inner = fixture_bundle(tmp_path)
    outer = tmp_path / 'artifact.zip'
    with zipfile.ZipFile(outer, 'w') as z:
        z.writestr('offline-analysis.zip', inner.read_bytes())
        z.writestr('test_results.xml', '<testsuites/>')
    manifest, files = read_bundle(outer)
    assert len(files) == 1 and manifest['dataset_kind'] == 'synthetic'


def test_tampered_result_rejected(tmp_path):
    original = fixture_bundle(tmp_path)
    altered = tmp_path / 'altered.zip'
    with zipfile.ZipFile(original) as old, zipfile.ZipFile(altered, 'w') as new:
        for name in old.namelist():
            new.writestr(name, old.read(name) if name == 'manifest.json' else b'changed')
    with pytest.raises(ValueError, match='checksum'): read_bundle(altered)


def test_unsafe_archive_paths_rejected_without_extracting(tmp_path):
    path = tmp_path / 'bad.zip'
    with zipfile.ZipFile(path, 'w') as z:
        z.writestr('../overwritten', 'untrusted')
    with pytest.raises(ValueError, match='Unsafe'): read_bundle(path)
    assert not (tmp_path.parent / 'overwritten').exists()


def test_fixture_outputs_cannot_be_labeled_real(tmp_path):
    (tmp_path / 'synthetic_scores.csv').write_text('fictional')
    with pytest.raises(ValueError, match='Synthetic'):
        create_bundle({'demo': tmp_path}, tmp_path / 'bad.zip', dataset_kind='real', source_commit='fixture')
