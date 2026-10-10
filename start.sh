#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if [[ ! -x .venv/bin/python || ! -d frontend/node_modules || ! -f data/processed/clinic_model.joblib ]]; then
  echo "Preparing local dependencies and recorded research data..."
  ./scripts/setup.sh
fi
mkdir -p .run
api_port="${GLUCOTWIN_API_PORT:-8765}"
ui_port="${GLUCOTWIN_UI_PORT:-5173}"
for port in "$api_port" "$ui_port"; do
  if lsof -iTCP:"$port" -sTCP:LISTEN -t >/dev/null 2>&1; then
    echo "Port $port is already in use. Stop that service or use the manual commands in README.md."
    exit 1
  fi
done
.venv/bin/python -m uvicorn backend.main:app --host 127.0.0.1 --port "$api_port" >.run/backend.log 2>&1 &
backend_pid=$!
(
  cd frontend
  export GLUCOTWIN_API_URL="http://127.0.0.1:$api_port"
  exec ./node_modules/.bin/vite --host 127.0.0.1 --port "$ui_port" --strictPort
) >.run/frontend.log 2>&1 &
frontend_pid=$!
cleanup() {
  kill "$backend_pid" "$frontend_pid" 2>/dev/null || true
}
trap cleanup EXIT INT TERM
echo "GlucoTwin: http://127.0.0.1:$ui_port"
echo "API documentation: http://127.0.0.1:$api_port/docs"
echo "Local login accounts are generated in .run/clinic-credentials.json (keep this file private)."
echo "Logs: .run/backend.log and .run/frontend.log"
echo "Press Ctrl+C to stop both services."
wait "$backend_pid" "$frontend_pid"
