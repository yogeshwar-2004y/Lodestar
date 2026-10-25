import uuid
from datetime import timedelta

from sqlalchemy import create_engine, text

from aseo.models.base import utcnow
from aseo.services import retention
from tests.conftest import OWNER_URL


def test_deleted_tenant_is_purged_after_grace_period(wp_site):
    api, site = wp_site
    tid = api.session["organization"]["id"]
    assert api.post("/organizations/current/deletion").status_code == 200
    # within grace period nothing happens
    assert tid not in retention.purge_deleted_tenants()
    purged = retention.purge_deleted_tenants(now=utcnow() + timedelta(days=31))
    assert tid in purged
    eng = create_engine(OWNER_URL)
    with eng.connect() as c:
        for table in ("sites", "audit_events", "approvals", "credit_ledger", "secret_blobs", "page_snapshots"):
            assert c.execute(text(f"select count(*) from {table} where tenant_id = :t"), {"t": tid}).scalar() == 0, table
    eng.dispose()
    assert api.get(f"/sites/{site['id']}").status_code in (401, 403, 404)


def test_snapshot_retention_keeps_latest(wp_site):
    api, site = wp_site
    from tests.conftest import drain

    api.post(f"/sites/{site['id']}/crawls", {})
    drain()
    eng = create_engine(OWNER_URL)
    with eng.begin() as c:
        c.execute(text("update tenants set data_retention_days = 0 where id = :t"), {"t": api.session["organization"]["id"]})
    retention.purge_snapshots()
    with eng.connect() as c:
        pages = c.execute(text("select count(*) from pages where site_id = :s"), {"s": site["id"]}).scalar()
        snaps = c.execute(text("select count(*) from page_snapshots ps join pages p on p.id = ps.page_id where p.site_id = :s"),
                          {"s": site["id"]}).scalar()
    eng.dispose()
    assert snaps == pages  # exactly the latest snapshot per page survives
    _ = uuid
