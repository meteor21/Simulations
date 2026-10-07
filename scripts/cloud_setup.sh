#!/usr/bin/env bash
set -euo pipefail
cd /workspace/Simulations
python3 -m venv /workspace/.venvs/midterm-sentiment
/workspace/.venvs/midterm-sentiment/bin/python -m pip install --cache-dir /workspace/.cache/pip -r requirements-dev.lock -e '.[dev]'
/workspace/.venvs/midterm-sentiment/bin/python -m pip check
