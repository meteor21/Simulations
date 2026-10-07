#!/usr/bin/env python3
"""Analyze one retained GitHub pilot run offline; never start or resume collection."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

from charisma_lab.pilot import run_pilot
from charisma_lab.transfer import create_bundle, read_bundle

MAX_ARTIFACT_BYTES = 128 * 1024 * 1024
MAX_CHECKPOINT_BYTES = 128 * 1024 * 1024
MAX_REPORT_BYTES = 2 * 1024 * 1024
KNOWN_PREFIXES = ('', 'live-pilot/', 'artifacts/live-pilot/')


def gh(*args):
    result = subprocess.run(['gh', *args], capture_output=True, text=True, timeout=180)
    if result.returncode:
        raise RuntimeError('GitHub artifact operation failed; no provider requests started')
    return result.stdout


def numeric_run_id(value):
    if isinstance(value, bool) or not re.fullmatch(r'[1-9][0-9]*', str(value)):
        raise ValueError('source-run-id must be a positive numeric GitHub run ID')
    return str(value)


def local_path(value):
    path = Path(value).expanduser().absolute()
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('Symlink output paths are not permitted')
    return path


def locate_artifact_file(root, filename, limit):
    """Read only recognized artifact layouts; reject links anywhere in the tree."""
    if root.is_symlink():
        raise ValueError('Artifact symlinks are not permitted')
    total = 0
    for item in root.rglob('*'):
        if item.is_symlink():
            raise ValueError('Artifact symlinks are not permitted')
        if item.is_file():
            total += item.stat().st_size
            if total > MAX_ARTIFACT_BYTES:
                raise ValueError('Downloaded artifact exceeds the size limit')
    matches = [root / (prefix + filename) for prefix in KNOWN_PREFIXES
               if (root / (prefix + filename)).is_file()]
    if len(matches) != 1:
        raise ValueError(f'Expected exactly one {filename} in a recognized artifact location')
    source = matches[0]
    if source.stat().st_size > limit:
        raise ValueError(f'{filename} exceeds the size limit')
    return source


def download_artifact(repository, run_id, name, destination, metadata):
    matches = [item for item in metadata['artifacts'] if item.get('name') == name]
    if len(matches) != 1 or matches[0].get('expired') is not False:
        raise ValueError(f'Required retained artifact {name} is missing, expired, or ambiguous for run {run_id}; no provider requests started')
    item = matches[0]
    size = item.get('size_in_bytes')
    if type(size) is not int or not 0 <= size <= MAX_ARTIFACT_BYTES:
        raise ValueError(f'Artifact {name} exceeds the download size limit or lacks size metadata')
    recorded_run = (item.get('workflow_run') or {}).get('id')
    if recorded_run is not None and str(recorded_run) != run_id:
        raise ValueError('Artifact belongs to a different source run')
    gh('run', 'download', run_id, '--repo', repository, '--name', name, '--dir', str(destination))


def completeness_notice(original):
    """Allowlist public summary fields; never print raw errors, headers, or bodies."""
    blockers = [str(value)[:300] for value in original.get('blockers', [])[:10]]
    resolutions = []
    for item in original.get('source_resolution', [])[:12]:
        if not isinstance(item, dict):
            continue
        record = {}
        for field in ('domain', 'status', 'error_type', 'http_status', 'source_id'):
            value = item.get(field)
            if isinstance(value, str):
                record[field] = value[:120]
            elif value is None or type(value) in (int, bool):
                record[field] = value
        resolutions.append(record)
    collection = original.get('run', {}).get('collection', {})
    counts = {key: value for key, value in collection.items()
              if key in {'processed', 'processed_hits', 'split', 'blocked', 'errors'} and type(value) is int}
    queue=[]
    for item in original.get('queue', [])[:20]:
        if isinstance(item, dict):
            queue.append({key: value[:80] if isinstance(value, str) else value
                          for key,value in item.items() if key in {'provider','status','jobs','n'}
                          and (isinstance(value,str) or type(value) is int)})
    summary = {'status': original.get('status'), 'blockers': blockers,
               'source_resolution': resolutions, 'collection': counts, 'queue': queue}
    for field in ('http_attempts_total','github_requests_reserved','selected_candidates'):
        if type(original.get(field)) is int: summary[field]=original[field]
    text = json.dumps(summary, ensure_ascii=True)[:6000]
    # Escape GitHub workflow-command control characters before writing a notice.
    text = text.replace('%', '%25').replace('\r', '%0D').replace('\n', '%0A')
    print('::notice title=Previous collection completeness::' + text)
    return summary


def analyze(source_run_id, output, bundle):
    run_id = numeric_run_id(source_run_id)
    repository = os.environ.get('GITHUB_REPOSITORY', '')
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository):
        raise ValueError('GITHUB_REPOSITORY must identify the source owner/repository')
    commit = os.environ.get('GITHUB_SHA', '')
    if not commit:
        raise ValueError('GITHUB_SHA is required to identify the analysis code revision')
    output = local_path(output)
    bundle = local_path(bundle)
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValueError('Refusing to overwrite existing analysis output or pilot database; use a dedicated empty folder')
    if bundle.suffix != '.zip' or bundle.exists():
        raise ValueError('Bundle must be a new ZIP path; existing files cannot be overwritten')

    metadata = json.loads(gh('api', f'repos/{repository}/actions/runs/{run_id}/artifacts?per_page=100'))
    if not isinstance(metadata, dict) or not isinstance(metadata.get('artifacts'), list):
        raise ValueError('Invalid GitHub artifact metadata; no provider requests started')
    if metadata.get('total_count', len(metadata['artifacts'])) > 100:
        raise ValueError('Source run has too many artifacts for this bounded reader')
    with tempfile.TemporaryDirectory(prefix='midterm-offline-analysis-') as temp:
        temp = Path(temp)
        state_dir, results_dir = temp / 'state', temp / 'results'
        download_artifact(repository, run_id, 'midterm-live-pilot-state', state_dir, metadata)
        download_artifact(repository, run_id, f'midterm-real-results-{run_id}', results_dir, metadata)
        source_db = locate_artifact_file(state_dir, 'pilot.sqlite', MAX_CHECKPOINT_BYTES)
        report_file = locate_artifact_file(results_dir, 'pilot_report.json', MAX_REPORT_BYTES)
        with source_db.open('rb') as source:
            if source.read(16) != b'SQLite format 3\x00':
                raise ValueError('Retained pilot.sqlite is not a SQLite checkpoint')
        if any(Path(str(source_db) + suffix).exists() for suffix in ('-wal', '-shm', '-journal')):
            raise ValueError('Checkpoint artifact contains active database sidecars')
        original = json.loads(report_file.read_text(encoding='utf-8'))
        if not isinstance(original, dict):
            raise ValueError('Original pilot report must be a JSON object')
        original_bundles=[results_dir / prefix / 'real-analysis.zip'
                          for prefix in ('', 'artifacts', 'live-pilot')
                          if (results_dir / prefix / 'real-analysis.zip').is_file()]
        if len(original_bundles)>1:
            raise ValueError('Original collection bundle is ambiguous')
        collection_commit=None
        if original_bundles:
            original_manifest,_=read_bundle(original_bundles[0])
            if original_manifest['dataset_kind']!='real':
                raise ValueError('Original collection bundle is not identified as real data')
            collection_commit=original_manifest.get('source_commit')
        summary = completeness_notice(original)
        output.mkdir(parents=True, exist_ok=True)
        # Exclusive create protects against a destination appearing after preflight.
        with source_db.open('rb') as source, (output / 'pilot.sqlite').open('xb') as target:
            shutil.copyfileobj(source, target)

    report = {'source_run_id': int(run_id), 'source_repository': repository,
              'collection_source_commit': collection_commit, 'analysis_source_commit': commit,
              'analysis_only': True, 'network_requested': False, 'provider_requests_made': 0,
              'original_pilot_report': original, 'original_completeness': summary,
              'analysis': None, 'bundle_created': False}
    try:
        report['analysis'] = run_pilot(output, analyze_existing=True)
        if report['analysis'].get('http_attempts_this_run', 0) != 0 or report['analysis'].get('network_requested', False):
            raise RuntimeError('Offline analysis returned inconsistent network accounting')
        if report['analysis'].get('blockers') or report['analysis'].get('analysis_only') is not True:
            raise RuntimeError('Saved checkpoint did not satisfy the original pilot analysis policy')
        create_bundle({'pilot': output, 'agents': output / 'exports'}, bundle,
                      dataset_kind='real', source_commit=commit)
        report['bundle_created'] = True
    except Exception as exc:
        report['analysis_error_type'] = type(exc).__name__
        raise RuntimeError('Offline checkpoint analysis failed (' + type(exc).__name__ +
                           '); original collection report retained in analysis_report.json') from None
    finally:
        (output / 'analysis_report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    analysis = report['analysis']
    observations = analysis.get('observations', {})
    print('::notice title=Saved real analysis::' + json.dumps({
        'status': analysis['status'], 'source_run_id': int(run_id),
        'selected_candidates': analysis.get('selected_candidates'),
        'unique_article_urls': observations.get('unique_article_urls'),
        'reviewed_annotations': observations.get('reviewed_annotations'),
        'http_attempts_total': analysis.get('http_attempts_total'),
        'provider_requests_made': 0, 'bundle_created': True}, sort_keys=True))
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-run-id', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--bundle', type=Path, required=True)
    args = parser.parse_args(argv)
    analyze(**vars(args))
    print('Offline retained-run analysis exported; zero provider requests made.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
