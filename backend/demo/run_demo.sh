#!/usr/bin/env bash
# Run the demo: a fictional candidate's job search, side by side with (and
# isolated from) the real app. Backend on :8001 against backend/demo.db with
# the example profile; frontend on :5174 proxying to it. Ctrl-C stops both.
#
#   backend/demo/run_demo.sh            # build demo.db if missing, then run
#   backend/demo/run_demo.sh --reseed   # rebuild demo.db first
set -euo pipefail
DEMO_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND="$(dirname "$DEMO_DIR")"
FRONTEND="$(dirname "$BACKEND")/frontend"

if [[ "${1:-}" == "--reseed" || ! -f "$BACKEND/demo.db" ]]; then
  "$BACKEND/.venv/bin/python" "$DEMO_DIR/seed_demo.py"
fi

cleanup() { kill 0 2>/dev/null || true; }
trap cleanup EXIT INT TERM

( cd "$BACKEND" && JOB_BOARD_DB="$BACKEND/demo.db" JOB_BOARD_PROFILE="$BACKEND/profile.example" USE_FIXTURES=1 \
    .venv/bin/python -m uvicorn app.main:app --port 8001 ) &
( cd "$FRONTEND" && API_TARGET="http://127.0.0.1:8001" npx vite --port 5174 --strictPort ) &

echo "Demo: http://localhost:5174  (backend :8001, database backend/demo.db)"
wait
