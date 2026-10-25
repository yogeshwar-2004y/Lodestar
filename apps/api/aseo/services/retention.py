"""Data retention and organization deletion.

* Snapshot retention: page snapshots older than the tenant's ``data_retention_days`` are
  deleted (the latest snapshot per page is always kept), along with stored HTML.
* Organization deletion: 30 days after ``deletion_requested_at`` the tenant and all of its
  rows are deleted (cascade). Append-only tables allow DELETE only inside this job, which
  sets ``app.retention_purge='on'`` for its transaction. Connector secrets are revoked first.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from sqlalchemy import delete, func, select, text

from aseo.core.db import system_session
from aseo.models import Connector, Page, PageSnapshot, Tenant
from aseo.models.base import utcnow
from aseo.services import secrets as secret_store
from aseo.services.storage import get_storage

log = logging.getLogger("aseo.retention")
DELETION_GRACE_DAYS = 30


def purge_snapshots() -> int:
    removed = 0
    with system_session() as db:
        for tenant in db.execute(select(Tenant)).scalars():
            cutoff = utcnow() - timedelta(days=tenant.data_retention_days)
            keep = select(Page.last_snapshot_id).where(Page.tenant_id == tenant.id, Page.last_snapshot_id.isnot(None))
            res = db.execute(delete(PageSnapshot).where(PageSnapshot.tenant_id == tenant.id, PageSnapshot.created_at < cutoff,
                                                        PageSnapshot.id.notin_(keep)))
            removed += res.rowcount or 0
    return removed


def purge_deleted_tenants(now: Any = None) -> list[str]:
    now = now or utcnow()
    purged: list[str] = []
    with system_session() as db:
        due = db.execute(select(Tenant).where(Tenant.deletion_requested_at.isnot(None),
                                              Tenant.deletion_requested_at < now - timedelta(days=DELETION_GRACE_DAYS))).scalars().all()
        for t in due:
            for c in db.execute(select(Connector).where(Connector.tenant_id == t.id)).scalars():
                secret_store.revoke_secrets(db, c.id)
            db.execute(text("select set_config('app.retention_purge', 'on', true)"))
            tid = t.id
            db.delete(t)
            db.flush()
            get_storage().delete_prefix(str(tid))
            purged.append(str(tid))
            log.info("tenant purged", extra={"tenant_id": str(tid)})
    return purged


def run_daily() -> dict[str, Any]:
    return {"snapshots_removed": purge_snapshots(), "tenants_purged": purge_deleted_tenants()}


_ = func
