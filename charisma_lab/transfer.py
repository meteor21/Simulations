"""Portable, checksummed tabular results for Colab; no databases or article bodies."""
from __future__ import annotations
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import zipfile

EXPORT_NAMES = {
    'candidate_registry.csv', 'candidate_cycles.csv', 'selected_congressional_cohort.csv',
    'selected_contest_memberships.csv', 'source_profiles.csv', 'source_bias_assessments.csv',
    'service_terms.csv', 'source_coverage.csv', 'observed_source_year_coverage.csv',
    'candidate_sentiment_summary.csv', 'candidate_sentiment_features.jsonl',
    'SYNTHETIC_demo_summary.json', 'synthetic_scores.csv', 'synthetic_scores.json', 'DATA_WARNING.txt',
}
MAX_BUNDLE_BYTES = 64 * 1024 * 1024


def create_bundle(folders, destination, *, dataset_kind, source_commit):
    """Package explicitly selected workflow exports, never a raw database/directory."""
    if dataset_kind not in {'synthetic', 'real'}:
        raise ValueError('Declare whether the results are synthetic or real')
    files = {}
    for label, folder in folders.items():
        if not re.fullmatch(r'[A-Za-z0-9_-]+', label):
            raise ValueError('Use a simple label for each export folder')
        folder = Path(folder)
        if not folder.is_dir():
            raise ValueError('Export folder does not exist')
        for name in sorted(EXPORT_NAMES):
            path = folder / name
            if path.is_file() and not path.is_symlink():
                if dataset_kind == 'real' and name.lower().startswith('synthetic'):
                    raise ValueError('Synthetic fixture files cannot be packaged as real results')
                files[label + '/' + name] = path.read_bytes()
    if not files:
        raise ValueError('No supported result files found')
    if sum(map(len, files.values())) > MAX_BUNDLE_BYTES:
        raise ValueError('Export exceeds the bounded bundle size')
    manifest = {'format': 'midterm-results-v1', 'dataset_kind': dataset_kind,
                'source_commit': source_commit, 'warning': 'Media portrayal is not public opinion. Missing is not neutral.',
                'files': {name: {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
                          for name, data in sorted(files.items())}}
    destination = Path(destination)
    if destination.suffix != '.zip':
        raise ValueError('Result bundle destination must be a ZIP, never a database')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('manifest.json', json.dumps(manifest, indent=2))
        for name, data in sorted(files.items()):
            archive.writestr(name, data)
    return manifest


def read_bundle(path):
    """Read in memory, verify checksums, and accept GitHub's one-level ZIP wrapper.

    Checksums detect corruption, not authenticity. Only import a trusted run's file.
    No archive member is executed or extracted to disk.
    """
    path = Path(path)
    if path.stat().st_size > MAX_BUNDLE_BYTES:
        raise ValueError('Bundle exceeds size limit')
    return _read_bytes(path.read_bytes(), allow_wrapper=True)


def _read_bytes(data, *, allow_wrapper):
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        infos = archive.infolist()
        names = [i.filename for i in infos]
        if len(infos) > 100 or len(names) != len(set(names)):
            raise ValueError('Too many or duplicate archive entries')
        if sum(i.file_size for i in infos) > MAX_BUNDLE_BYTES:
            raise ValueError('Uncompressed bundle exceeds size limit')
        for item in infos:
            name = PurePosixPath(item.filename)
            if name.is_absolute() or '..' in name.parts or '\\' in item.filename:
                raise ValueError('Unsafe archive member')
            if (item.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError('Archive links are not supported')
        if 'manifest.json' not in names:
            nested = [name for name in ('offline-analysis.zip', 'real-analysis.zip') if name in names]
            if allow_wrapper and len(nested) == 1:
                return _read_bytes(archive.read(nested[0]), allow_wrapper=False)
            raise ValueError('Not a Midterm results bundle')
        manifest = json.loads(archive.read('manifest.json'))
        if manifest.get('format') != 'midterm-results-v1' or manifest.get('dataset_kind') not in {'synthetic', 'real'}:
            raise ValueError('Unknown results format')
        entries = manifest.get('files')
        if not isinstance(entries, dict) or set(names) != {'manifest.json', *entries}:
            raise ValueError('Manifest and archive file list differ')
        files = {}
        for name, expected in entries.items():
            parts = PurePosixPath(name).parts
            if len(parts) != 2 or parts[1] not in EXPORT_NAMES:
                raise ValueError('Unsupported export file')
            content = archive.read(name)
            if len(content) != expected['bytes'] or hashlib.sha256(content).hexdigest() != expected['sha256']:
                raise ValueError('Result checksum mismatch')
            files[name] = content
        return manifest, files
