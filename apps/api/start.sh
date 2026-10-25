#!/bin/sh
# Container entrypoint: migrate, start the API on $PORT, optionally seed demo data once it is up.
set -e
alembic upgrade head
if [ "${SEED_DEMO:-false}" = "true" ]; then
  (sleep 25 && python -m aseo.seed || echo "demo seed skipped/failed (re-run later)") &
fi
exec uvicorn aseo.main:app --host 0.0.0.0 --port "${PORT:-8400}" --proxy-headers --forwarded-allow-ips="*"
