#!/usr/bin/env python3
"""Restore one known pilot artifact via gh; missing archives never reset the remote quota."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile
import shutil


def gh(*args):
    result = subprocess.run(['gh', *args], capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError('Cannot inspect/download prior GitHub pilot state; no provider requests started')
    return result.stdout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    repository = os.environ['GITHUB_REPOSITORY']
    data = json.loads(gh('api', f'repos/{repository}/actions/artifacts?name=midterm-live-pilot-state&per_page=100'))
    available = [a for a in data['artifacts'] if not a['expired'] and a['name'] == 'midterm-live-pilot-state']
    if not available:
        print('No retained checkpoint; any previously spent requests remain charged in midterm-pilot-budget.')
        return
    newest = max(available, key=lambda a: a['id'])
    with tempfile.TemporaryDirectory(prefix='midterm-checkpoint-') as temp:
        gh('run', 'download', str(newest['workflow_run']['id']), '--repo', repository,
           '--name', 'midterm-live-pilot-state', '--dir', temp)
        source = Path(temp) / 'pilot.sqlite'
        if not source.is_file() or source.is_symlink():
            raise ValueError('Expected pilot checkpoint is missing')
        args.output.mkdir(parents=True, exist_ok=True)
        target = args.output / 'pilot.sqlite'
        if target.exists():
            raise ValueError('Refusing to overwrite existing local pilot state')
        shutil.copyfile(source, target)
    print('Restored pilot state from run', newest['workflow_run']['id'])


if __name__ == '__main__':
    main()
