#!/usr/bin/env python3
"""Publish an owned GitHub visual-report branch; this does not enable/deploy Pages."""
from __future__ import annotations

import argparse
import base64
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

BRANCH = 'analysis-dashboard'
FORMAT = 'midterm-public-dashboard-v1'
MARKER = '.midterm-dashboard.json'
ALLOWED_FILES = frozenset({'index.html', 'data.json', 'candidate_coverage.csv', 'README.md',
                          'coverage.svg', 'pipeline.svg', 'budget.svg', '.nojekyll', MARKER})
REQUIRED_FILES = frozenset({'index.html', 'README.md', MARKER})
MAX_TOTAL_BYTES = 20 * 1024 * 1024
MAX_MARKER_BYTES = 64 * 1024


class GitHubApiError(RuntimeError):
    def __init__(self, status=None):
        self.status = status
        suffix = f' (HTTP {status})' if status is not None else ''
        super().__init__('GitHub publication API operation failed' + suffix)


def api(method, endpoint, payload=None):
    """Use gh's injected authentication; never copy tokens into argv or output."""
    command = ['gh', 'api', '--method', method, '--include', endpoint]
    temporary = None
    try:
        if payload is not None:
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', suffix='.json', delete=False) as stream:
                json.dump(payload, stream, ensure_ascii=False)
                temporary = Path(stream.name)
            command += ['--input', str(temporary)]
        result = subprocess.run(command, capture_output=True, text=True, timeout=90)
        headers, separator, body = result.stdout.replace('\r\n', '\n').partition('\n\n')
        match = re.search(r'^HTTP/\S+\s+(\d{3})\b', headers)
        status = int(match.group(1)) if match else None
        if result.returncode or status is None or not 200 <= status < 300:
            raise GitHubApiError(status)
        if not separator:
            raise GitHubApiError(status)
        try:
            return json.loads(body)
        except (ValueError, TypeError):
            raise GitHubApiError(status) from None
    except (OSError, subprocess.TimeoutExpired):
        raise GitHubApiError() from None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def safe_path(value):
    path = Path(value).expanduser().absolute()
    if any(parent.is_symlink() for parent in (path, *path.parents)):
        raise ValueError('Symlink publication paths are not permitted')
    return path


def validate_marker(value, repository):
    if not isinstance(value, dict) or value.get('format') != FORMAT:
        raise ValueError('Dashboard ownership marker has an unsupported format')
    owner = value.get('source_repository')
    if not isinstance(owner, str) or owner.casefold() != repository.casefold():
        raise ValueError('Dashboard ownership marker belongs to a different repository')


def load_site(site, repository):
    root = safe_path(site)
    if not root.is_dir():
        raise ValueError('Dashboard directory does not exist')
    entries = list(root.iterdir())
    if any(entry.is_symlink() for entry in entries):
        raise ValueError('Dashboard symlinks are not permitted')
    if any(not entry.is_file() or entry.name not in ALLOWED_FILES for entry in entries):
        raise ValueError('Dashboard contains unsupported files or directories')
    names = {entry.name for entry in entries}
    if not REQUIRED_FILES <= names:
        raise ValueError('Dashboard requires index.html, README.md, and its ownership marker')
    total = sum(entry.stat().st_size for entry in entries)
    if total > MAX_TOTAL_BYTES or (root / MARKER).stat().st_size > MAX_MARKER_BYTES:
        raise ValueError('Dashboard exceeds its publication size limit')
    contents = {}
    try:
        actual_total = 0
        for entry in entries:
            with entry.open('rb') as stream:
                data = stream.read(MAX_TOTAL_BYTES - actual_total + 1)
            actual_total += len(data)
            if actual_total > MAX_TOTAL_BYTES:
                raise ValueError('Dashboard exceeds its publication size limit')
            contents[entry.name] = data.decode('utf-8')
        marker = json.loads(contents[MARKER])
    except (UnicodeError, ValueError):
        raise ValueError('Dashboard files must be UTF-8 with a valid JSON ownership marker') from None
    # Recheck actual content sizes in case a producer changed files after stat.
    total = sum(len(value.encode('utf-8')) for value in contents.values())
    if total > MAX_TOTAL_BYTES:
        raise ValueError('Dashboard exceeds its publication size limit')
    validate_marker(marker, repository)
    return contents, total


def sha(value):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9a-f]{40}', value):
        raise ValueError('GitHub returned an invalid Git object identifier')
    return value


def inspect_owned_head(repository):
    refs = api('GET', f'repos/{repository}/git/matching-refs/heads/{BRANCH}')
    if not isinstance(refs, list):
        raise ValueError('GitHub returned unexpected branch metadata')
    matches = [ref for ref in refs if ref.get('ref') == f'refs/heads/{BRANCH}']
    if not matches:
        return None
    if len(matches) != 1 or matches[0].get('object', {}).get('type') != 'commit':
        raise ValueError('Dashboard branch has unexpected reference metadata')
    head = sha(matches[0]['object']['sha'])
    try:
        marker_file = api('GET', f'repos/{repository}/contents/{MARKER}?ref={head}')
    except GitHubApiError:
        raise ValueError('Existing dashboard branch ownership cannot be verified; no branch changes made') from None
    if (marker_file.get('type') != 'file' or marker_file.get('encoding') != 'base64'
            or type(marker_file.get('size')) is not int or not 0 <= marker_file['size'] <= MAX_MARKER_BYTES):
        raise ValueError('Existing dashboard branch lacks a valid ownership marker')
    try:
        encoded = marker_file.get('content', '')
        if not isinstance(encoded, str) or len(encoded) > 2 * MAX_MARKER_BYTES:
            raise ValueError
        decoded = base64.b64decode(''.join(encoded.split()), validate=True)
        if len(decoded) > MAX_MARKER_BYTES:
            raise ValueError
        marker = json.loads(decoded)
    except (ValueError, UnicodeError):
        raise ValueError('Existing dashboard branch ownership marker is invalid') from None
    validate_marker(marker, repository)
    commit = api('GET', f'repos/{repository}/git/commits/{head}')
    return {'sha': head, 'tree': sha(commit.get('tree', {}).get('sha'))}


def publish(site, report_path=None):
    repository = os.environ.get('GITHUB_REPOSITORY', '')
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository):
        raise ValueError('GITHUB_REPOSITORY must name the publication repository')
    contents, total = load_site(site, repository)
    report_path = safe_path(report_path) if report_path is not None else None
    if report_path is not None and (report_path.suffix != '.json' or report_path.exists()):
        raise ValueError('Publication report must use a new JSON path; existing files cannot be overwritten')
    head = inspect_owned_head(repository)
    for attempt in range(2):
        tree_payload = {'tree': [{'path': name, 'mode': '100644', 'type': 'blob', 'content': content}
                                 for name, content in sorted(contents.items())]}
        if head is not None:
            tree_payload['base_tree'] = head['tree']  # Preserve unrelated existing branch files.
        tree = api('POST', f'repos/{repository}/git/trees', tree_payload)
        commit = api('POST', f'repos/{repository}/git/commits',
                     {'message': 'Publish saved-data Midterm Sentiment visual report',
                      'tree': sha(tree.get('sha')), 'parents': [head['sha']] if head else []})
        new_sha = sha(commit.get('sha'))
        try:
            if head is None:
                published = api('POST', f'repos/{repository}/git/refs',
                                {'ref': f'refs/heads/{BRANCH}', 'sha': new_sha})
            else:
                published = api('PATCH', f'repos/{repository}/git/refs/heads/{BRANCH}',
                                {'sha': new_sha, 'force': False})
        except GitHubApiError as exc:
            if attempt or exc.status not in {409, 422}:
                raise
            # Retry only if the branch actually advanced and its new marker is ours.
            advanced = inspect_owned_head(repository)
            if advanced is None or (head is not None and advanced['sha'] == head['sha']):
                raise GitHubApiError(exc.status) from None
            head = advanced
            continue
        if published.get('object', {}).get('sha') != new_sha:
            raise ValueError('GitHub did not confirm the expected published branch commit')
        break
    report = {'status': 'published', 'repository': repository, 'branch': BRANCH,
              'commit': new_sha, 'files': sorted(contents), 'total_bytes': total,
              'publication_attempts': attempt + 1, 'pages_deployed': False,
              'rendered_report_url': f'https://github.com/{repository}/tree/{BRANCH}',
              'html_source_url': f'https://github.com/{repository}/blob/{BRANCH}/index.html'}
    if report_path is not None:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        with report_path.open('x', encoding='utf-8') as stream:
            json.dump(report, stream, indent=2)
    print('::notice title=GitHub visual report published::' + report['rendered_report_url'] +
          ' — rendered repository report; GitHub Pages deployment is separate.')
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--site', type=Path, required=True)
    parser.add_argument('--report', type=Path)
    args = parser.parse_args(argv)
    publish(args.site, args.report)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
