# -*- mode: sh; sh-shell: bash -*-
# One-command local run: venv check -> deps -> migrate -> seed -> API -> worker.
# Usage:  ./run.sh            (server only)
#         ./run.sh worker     (background-job worker only)
set -euo pipefail

PY=${PY:-python3}
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  $PY -m venv .venv
  ./.venv/bin/pip install --quiet -r requirements.txt -r requirements-dev.txt
fi

if [ ! -f .env ]; then
  cp .env.example .env
  echo "[run] created .env from .env.example — edit SECRET_KEY!"
fi

./.venv/bin/python -m alembic upgrade head

if [ "${1:-}" = "worker" ]; then
  exec ./.venv/bin/python -m app.services.worker
fi

./.venv/bin/python -m app.seed || true
echo "[run] API on http://localhost:8000 — healthz: http://localhost:8000/healthz"
echo "[run] customer site (different origin):"
echo "      python3 -m http.server 5500 --directory website  ->  http://localhost:5500/customer-site.html"
exec ./.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"