#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

# Python 3.12+ and Node 20+ are the only prerequisites; no paid service is used.
if [[ ! -x .venv/bin/python ]]; then
  "${GLUCOTWIN_PYTHON:-python3}" -m venv .venv
fi
.venv/bin/python -m pip install -r requirements-lock.txt
if [[ -f frontend/package-lock.json ]]; then
  npm --prefix frontend ci
else
  npm --prefix frontend install
fi
.venv/bin/python scripts/prepare_data.py
.venv/bin/python scripts/evaluate.py
echo "GlucoTwin is ready. Start it with ./start.sh"
