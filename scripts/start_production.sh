#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ ! -x .venv/bin/python || ! -f frontend/dist/index.html || ! -f data/processed/clinic_model.joblib ]]; then
  ./scripts/setup.sh
fi
port="${GLUCOTWIN_API_PORT:-8765}"
if lsof -iTCP:"$port" -sTCP:LISTEN -t >/dev/null 2>&1; then
  echo "Port $port is occupied. Choose GLUCOTWIN_API_PORT or stop that service."
  exit 1
fi
echo "GlucoTwin compiled local demo: http://127.0.0.1:$port"
echo "Local accounts: .run/clinic-credentials.json. No public deployment is implied."
exec .venv/bin/python -m uvicorn backend.main:app --host 127.0.0.1 --port "$port"
