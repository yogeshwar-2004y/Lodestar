#!/usr/bin/env bash
# Backup/restore drill: dump the database, restore into a scratch DB, and verify integrity
# (row counts, every tenant's audit hash chain, credit-ledger reconciliation).
# Usage: scripts/backup_restore_check.sh [source_db]   (requires pg_dump/pg_restore/psql)
set -euo pipefail
SRC=${1:-aseo}
DST="${SRC}_restore_check"
DUMP=$(mktemp -t aseo-backup).dump
PGBIN=${PGBIN:-$(dirname "$(command -v pg_dump)")}
"$PGBIN/pg_dump" -Fc -d "$SRC" -f "$DUMP"
"$PGBIN/dropdb" --if-exists "$DST"
"$PGBIN/createdb" "$DST"
"$PGBIN/pg_restore" -d "$DST" --no-owner "$DUMP" >/dev/null
for t in tenants sites change_sets approvals audit_events credit_ledger; do
  a=$("$PGBIN/psql" -Atd "$SRC" -c "select count(*) from $t"); b=$("$PGBIN/psql" -Atd "$DST" -c "select count(*) from $t")
  [ "$a" = "$b" ] || { echo "MISMATCH $t: $a vs $b"; exit 1; }
  echo "rows ok  $t=$a"
done
DATABASE_URL="postgresql+psycopg://localhost:5432/$DST" DATABASE_APP_URL="postgresql+psycopg://localhost:5432/$DST" \
  PYTHONPATH=apps/api apps/api/.venv/bin/python - <<'PY'
from sqlalchemy import select
from aseo.core.db import system_session
from aseo.models import Tenant
from aseo.services import audit, billing
with system_session() as db:
    for t in db.execute(select(Tenant)).scalars():
        chain, ledger = audit.verify_chain(db, t.id), billing.reconcile(db, t.id)
        assert chain["valid"] and ledger["consistent"], (t.slug, chain, ledger)
        print(f"verified {t.slug}: audit events={chain['checked']} ledger entries={ledger['entries']}")
PY
"$PGBIN/dropdb" "$DST"; rm -f "$DUMP"
echo "backup/restore drill passed"
