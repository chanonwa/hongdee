#!/usr/bin/env bash
# One-command start: install deps, seed demo data, run the server.
set -euo pipefail
cd "$(dirname "$0")"

PY=${PYTHON:-python3}

echo "→ installing dependencies"
$PY -m pip install -q -r requirements.txt

if [ ! -f hongdee.db ]; then
  echo "→ seeding demo portfolio (this takes ~30s)"
  $PY -m backend.seed
fi

echo "→ starting HongDee on http://127.0.0.1:8000"
echo "  sign in with admin@hongdee.co.uk / admin1234"
exec $PY -m uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
