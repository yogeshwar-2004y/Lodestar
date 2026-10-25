"""Idempotent demo seed: `python -m aseo.seed`.

Creates clearly-labelled demo data:
* demo@lodestar.example / demo-password-123 — owner of "Northwind Coffee (Demo)" with a
  WordPress *fixture* site (requires the fixture server on WP_FIXTURE_URL), verified,
  crawled, agents run, demo Search Console data.
* agency@lodestar.example / demo-password-123 — an agency org with two client workspaces and
  a client user client@lodestar.example limited to one workspace.
"""

from __future__ import annotations

import os
import sys

from sqlalchemy import select

from aseo.core.db import new_session, set_session_tenant
from aseo.models import ClientWorkspace, Membership, Site, User, WorkspaceMembership
from aseo.services import connectors as connector_svc
from aseo.services import crawls, gsc, outbox, tenancy
from aseo.services import sites as site_svc

PASSWORD = "demo-password-123"  # noqa: S105 — demo fixture credential, demo mode only
WP_URL = os.environ.get("WP_FIXTURE_URL", "http://127.0.0.1:8481")


def _user(db, email: str, name: str) -> tuple[User, bool]:
    u = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    return (u, False) if u else (tenancy.create_user(db, email=email, name=name, password=PASSWORD), True)


def main() -> None:
    import aseo.agents.workflows  # noqa: F401 — register handlers
    import aseo.services.changes  # noqa: F401
    from aseo.core.config import get_settings

    if not get_settings().demo_mode or get_settings().environment == "production":
        sys.exit("Refusing to seed: DEMO_MODE must be on and ENVIRONMENT must not be production.")
    db = new_session()
    try:
        crawls.sync_rule_catalogue(db)
        demo, created = _user(db, "demo@lodestar.example", "Demo Owner")
        if created:
            tenant, _ = tenancy.create_organization(db, owner=demo, name="Northwind Coffee (Demo)", kind="business", is_demo=True)
        else:
            tenant_id = db.execute(select(Membership.tenant_id).where(Membership.user_id == demo.id)).scalars().first()
            set_session_tenant(db, tenant_id)
            tenant = None
        tid = tenant.id if tenant else tenant_id
        site = db.execute(select(Site).where(Site.tenant_id == tid)).scalars().first()
        if site is None:
            site = site_svc.create_site(db, tenant_id=tid, actor_id=demo.id, actor_label=demo.email, name="Northwind Coffee (fixture)", url=WP_URL,
                                        platform="wordpress", workspace_id=None, is_demo=True,
                                        business_goals="Grow coffee subscription sign-ups; improve how guides appear in search.")
            site_svc.start_verification(db, site, "connector")
            site_svc.push_fixture_token(db, site)
            c = connector_svc.connect(db, site=site, provider="wordpress", mode="fixture", config={"username": "lodestar-agent"},
                                      secrets={"app_password": "fixture-app-password"})
            if c.status != "connected":
                print(f"! WordPress fixture not reachable at {WP_URL}: {c.last_error}. Start it with `make fixture` and re-run.")
            else:
                v = site_svc.check_verification(db, site, site_svc.latest_verification(db, site))
                print(f"verification: {v.status}")
            crawls.schedule_crawl(db, site, trigger="onboarding", requested_by=demo.id)
            gsc.connect_fixture(db, site, demo.id)
        db.commit()

        agency, created = _user(db, "agency@lodestar.example", "Avery Agency")
        if created:
            at, _ = tenancy.create_organization(db, owner=agency, name="Brightline Digital (Demo agency)", kind="agency", is_demo=True)
            at.branding = {"agency_name": "Brightline Digital", "primary_color": "#0f8f83"}
            ws_a = ClientWorkspace(tenant_id=at.id, name="Harbor Bakery", slug="harbor-bakery", branding={"primary_color": "#b45309"})
            ws_b = ClientWorkspace(tenant_id=at.id, name="Summit Outfitters", slug="summit-outfitters", branding={"primary_color": "#2563eb"})
            db.add_all([ws_a, ws_b])
            db.flush()
            for ws, domain in ((ws_a, "harbor-bakery.example"), (ws_b, "summit-outfitters.example")):
                site_svc.create_site(db, tenant_id=at.id, actor_id=agency.id, actor_label=agency.email, name=ws.name, url=f"https://{domain}",
                                     platform="public", workspace_id=ws.id, is_demo=True)
            client, _ = _user(db, "client@lodestar.example", "Casey Client")
            db.add(Membership(tenant_id=at.id, user_id=client.id, role="client"))
            db.add(WorkspaceMembership(tenant_id=at.id, workspace_id=ws_a.id, user_id=client.id, role="client"))
        db.commit()
    finally:
        db.close()
    n = outbox.drain()
    print(f"processed {n} background jobs")
    print(f"Demo users (password {PASSWORD}): demo@lodestar.example, agency@lodestar.example, client@lodestar.example")


if __name__ == "__main__":
    main()
