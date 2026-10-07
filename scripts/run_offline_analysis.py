#!/usr/bin/env python3
"""Run the existing synthetic analyses and export a portable Colab results bundle."""
import argparse
import json
from pathlib import Path
import runpy
import subprocess
from charisma_lab.transfer import create_bundle


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('artifacts'))
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    agents = runpy.run_path(str(root / 'examples/agents_demo.py'))['run_demo'](output / 'agents')
    standing = runpy.run_path(str(root / 'examples/offline_demo.py'))['run_demo'](output / 'standing')
    result = subprocess.run(['git', 'rev-parse', '--verify', 'HEAD'], cwd=root, capture_output=True, text=True)
    commit = result.stdout.strip() if result.returncode == 0 else 'uncommitted-workspace'
    dirty = subprocess.run(['git', 'status', '--porcelain'], cwd=root, capture_output=True, text=True)
    if result.returncode == 0 and dirty.stdout.strip(): commit += '+local-changes'
    manifest = create_bundle({'agents': output / 'agents/exports', 'summary': output / 'agents',
                              'standing': output / 'standing'}, output / 'offline-analysis.zip',
                             dataset_kind='synthetic', source_commit=commit)
    print(json.dumps({'dataset_kind': 'synthetic', 'agent_results': agents,
                      'standing_rows': len(standing), 'bundle_files': len(manifest['files']),
                      'source_commit': commit, 'bundle': str(output / 'offline-analysis.zip')}, indent=2))


if __name__ == '__main__':
    main()
