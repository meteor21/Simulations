#!/usr/bin/env python3
"""Execute every default notebook cell in a fresh kernel with network blocked."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import nbformat
from nbclient import NotebookClient


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', type=Path, default=Path('reports/notebook_execution.json'))
    parser.add_argument('--results-bundle', type=Path, help='Also execute the results-import cell with this bundle')
    args = parser.parse_args()
    if args.results_bundle:
        bundle = args.results_bundle.resolve(strict=True)
        os.environ['MIDTERM_RESULTS_BUNDLE'] = str(bundle)
    else:
        os.environ.pop('MIDTERM_RESULTS_BUNDLE', None)
    root = Path(__file__).resolve().parents[1]
    subprocess.run([sys.executable, str(root / 'scripts/sync_notebook.py'), '--check'], check=True)
    notebook = nbformat.read(root / 'notebooks/Midterm_Sentiment_Agents_Colab.ipynb', as_version=4)
    # Guard against accidental HTTP or sockets from future changes. This is an extra
    # test-only setup cell; the 13 notebook code cells themselves remain unmodified.
    guard = nbformat.v4.new_code_cell(f'import sys\nassert sys.executable == {sys.executable!r}, "Wrong notebook interpreter"\n' + '''import socket, requests, urllib.request
_network_attempts = []
def _deny_network(*args, **kwargs):
    _network_attempts.append(True)
    raise RuntimeError("Offline notebook validation forbids network access")
requests.sessions.Session.request = _deny_network
urllib.request.urlopen = _deny_network
_original_connect = socket.socket.connect
def _offline_connect(self, address):
    if isinstance(address, tuple) and address[0] not in ("127.0.0.1", "::1", "localhost"):
        return _deny_network()
    return _original_connect(self, address)
socket.socket.connect = _offline_connect
''')
    notebook.cells.insert(0, guard)
    notebook.cells.append(nbformat.v4.new_code_cell('assert not _network_attempts, "Offline workflow attempted network access"'))
    if args.results_bundle:
        notebook.cells[-1].source += '\nassert RESULTS_TABLES, "Result bundle import did not produce tables"'
    with tempfile.TemporaryDirectory(prefix='midterm-notebook-') as work:
        runtime = Path(work) / 'jupyter'
        runtime.mkdir()
        os.environ['JUPYTER_RUNTIME_DIR'] = str(runtime)
        os.environ['IPYTHONDIR'] = str(Path(work) / 'ipython')
        client = NotebookClient(notebook, timeout=120, kernel_name='python3', resources={'metadata': {'path': work}})
        client.km = client.create_kernel_manager()
        client.km.kernel_spec.argv[0] = sys.executable
        client.execute()
    counts = [c for c in notebook.cells[1:-1] if c.cell_type == 'code']
    report = {'method': 'nbclient fresh kernel; unmodified defaults plus network-denial guards',
              'notebook_code_cells': len(counts), 'total_notebook_cells': len(notebook.cells)-2,
              'executed_code_cells': sum(c.execution_count is not None for c in counts),
              'errors': [o for c in counts for o in c.outputs if o.output_type == 'error'],
              'network_attempts': 0, 'python': sys.version, 'kernel_executable': sys.executable,
              'bundle_import_checked': bool(args.results_bundle),
              'notebook_sha256': hashlib.sha256((root / 'notebooks/Midterm_Sentiment_Agents_Colab.ipynb').read_bytes()).hexdigest()}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
