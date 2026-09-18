#!/usr/bin/env bash
# AutoPivot - start the API and website on macOS/Linux.
# Run setup.sh once before using this script.

set -euo pipefail
cd "$(dirname "$0")"

if [[ ! -x ".venv/bin/python" ]]; then
  echo "ERROR: no virtual environment found. Run: bash setup.sh" >&2
  exit 1
fi

if [[ ! -d "frontend/node_modules" ]]; then
  echo "ERROR: frontend dependencies are not installed. Run: npm install --prefix frontend" >&2
  exit 1
fi

source .venv/bin/activate

api_pid=""
frontend_pid=""
cleanup() {
  trap - EXIT INT TERM
  [[ -n "$frontend_pid" ]] && kill "$frontend_pid" 2>/dev/null || true
  [[ -n "$api_pid" ]] && kill "$api_pid" 2>/dev/null || true
  wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo "Starting AutoPivot ..."
echo "  API      http://127.0.0.1:8000"
echo "  Website  http://localhost:5173"

python autopivot_backend.py &
api_pid=$!
sleep 3

npm run dev --prefix frontend &
frontend_pid=$!
sleep 2

if command -v open >/dev/null 2>&1; then
  open http://localhost:5173 || true
elif command -v xdg-open >/dev/null 2>&1; then
  xdg-open http://localhost:5173 >/dev/null 2>&1 || true
fi

echo "AutoPivot is running. Press Ctrl+C to stop both processes."
wait "$api_pid"
