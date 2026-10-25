"""Sites and domain-ownership verification."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from aseo.connectors.registry import get_connector
from aseo.core.config import get_settings
from aseo.core.errors import Conflict, ConnectorError, NotFound, ValidationFailed
from aseo.core.security import constant_time_eq, new_token
from aseo.crawler.netguard import BlockedDestination, safe_fetch
from aseo.crawler.urls import InvalidURL, domain_from_input
from aseo.models import AutomationSchedule, ClientWorkspace, Connector, Site, SiteVerification
from aseo.models.base import utcnow
from aseo.services import audit, billing
from aseo.services import connectors as connector_svc
from aseo.services.changes import ensure_policy

META_NAME = "lodestar-site-verification"
WELL_KNOWN = "/.well-known/lodestar-verification.txt"


def create_site(db: Session, *, tenant_id: uuid.UUID, actor_id: uuid.UUID | None, actor_label: str, name: str, url: str,
                platform: str, workspace_id: uuid.UUID | None, crawl_settings: dict[str, Any] | None = None,
                business_goals: str | None = None, is_demo: bool = False) -> Site:
    try:
        domain, base_url = domain_from_input(url)
    except InvalidURL as exc:
        raise ValidationFailed(f"Invalid website URL: {exc}") from exc
    if platform not in ("wordpress", "shopify", "github", "public"):
        raise ValidationFailed("Unsupported platform")
    if db.execute(select(Site).where(Site.tenant_id == tenant_id, Site.domain == domain)).scalar_one_or_none():
        raise Conflict("This website is already registered in your organization.", code="site_exists")
    billing.enforce_site_quota(db, tenant_id)
    if workspace_id is None:
        workspace_id = db.execute(select(ClientWorkspace.id).where(ClientWorkspace.tenant_id == tenant_id,
                                                                   ClientWorkspace.is_default.is_(True))).scalar_one_or_none()
    elif db.get(ClientWorkspace, workspace_id) is None:
        raise NotFound("Workspace not found")
    settings = {"max_pages": 100, "max_depth": 6, "include_paths": [], "exclude_paths": [], "respect_robots": True,
                **(crawl_settings or {})}
    site = Site(tenant_id=tenant_id, workspace_id=workspace_id, name=name.strip() or domain, domain=domain, base_url=base_url,
                platform=platform, status="pending", crawl_settings=settings, business_goals=business_goals, is_demo=is_demo)
    db.add(site)
    db.flush()
    ensure_policy(db, site)
    db.add(AutomationSchedule(tenant_id=tenant_id, site_id=site.id, kind="crawl", interval_minutes=7 * 24 * 60, enabled=True,
                              next_run_at=None))
    audit.record(db, tenant_id=tenant_id, action="site.created", actor_id=actor_id, actor_label=actor_label, target_type="site",
                 target_id=site.id, site_id=site.id, data={"domain": domain, "platform": platform})
    return site


def instructions(method: str, token: str, site: Site) -> dict[str, Any]:
    if method == "meta_tag":
        return {"method": method, "steps": [f'Add this tag inside <head> of {site.base_url}:'],
                "value": f'<meta name="{META_NAME}" content="{token}">'}
    if method == "dns_txt":
        return {"method": method, "steps": [f"Add a TXT record on {site.domain.split(':')[0]}:"], "value": f"{META_NAME}={token}"}
    if method == "well_known_file":
        return {"method": method, "steps": [f"Serve a text file at {site.base_url.rstrip('/')}{WELL_KNOWN} containing:"], "value": token}
    if method == "connector":
        return {"method": method, "steps": ["Open WordPress → Settings → Lodestar and paste this verification token, then connect the plugin:"],
                "value": token}
    raise ValidationFailed("Unknown verification method")


def start_verification(db: Session, site: Site, method: str) -> tuple[SiteVerification, dict[str, Any]]:
    token = f"ls-{new_token(18)}"
    v = SiteVerification(tenant_id=site.tenant_id, site_id=site.id, method=method, token=token, status="pending")
    db.add(v)
    db.flush()
    return v, instructions(method, token, site)


async def _check_meta(site: Site, token: str) -> tuple[bool, dict[str, Any]]:
    res = await safe_fetch(site.base_url)
    if res.status_code != 200:
        return False, {"status": res.status_code}
    from selectolax.parser import HTMLParser

    tree = HTMLParser(res.text)
    values = [n.attributes.get("content") or "" for n in tree.css(f'meta[name="{META_NAME}"]')]
    return any(constant_time_eq(v.strip(), token) for v in values), {"found_tags": len(values), "status": res.status_code}


async def _check_file(site: Site, token: str) -> tuple[bool, dict[str, Any]]:
    res = await safe_fetch(site.base_url.rstrip("/") + WELL_KNOWN, max_bytes=4096)
    ok = res.status_code == 200 and constant_time_eq(res.text.strip(), token)
    return ok, {"status": res.status_code}


async def _check_dns(site: Site, token: str) -> tuple[bool, dict[str, Any]]:
    host = site.domain.split(":")[0]
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get("https://cloudflare-dns.com/dns-query", params={"name": host, "type": "TXT"},
                             headers={"accept": "application/dns-json"})
    answers = [a.get("data", "").strip('"') for a in r.json().get("Answer", [])]
    expected = f"{META_NAME}={token}"
    return any(constant_time_eq(a, expected) for a in answers), {"txt_records": len(answers)}


def check_verification(db: Session, site: Site, verification: SiteVerification) -> SiteVerification:
    if verification.status == "verified":
        return verification
    try:
        if verification.method == "meta_tag":
            ok, evidence = connector_svc.run(_check_meta(site, verification.token))
        elif verification.method == "well_known_file":
            ok, evidence = connector_svc.run(_check_file(site, verification.token))
        elif verification.method == "dns_txt":
            ok, evidence = connector_svc.run(_check_dns(site, verification.token))
        elif verification.method == "connector":
            connector = connector_svc.write_connector_for(db, site)
            if connector is None:
                raise ValidationFailed("Connect the platform first, then check verification.")
            info = connector_svc.run(get_connector(connector.provider).verify_ownership(connector_svc.build_context(db, site, connector)))
            remote = str(info.get("verification_token") or "")
            token_ok = bool(remote) and constant_time_eq(remote, verification.token)
            # Shopify/GitHub: an authorized platform credential whose primary domain matches the site
            domain_ok = connector.provider in ("shopify", "github") and info.get("domain_match") is True
            ok = token_ok or domain_ok
            evidence = {"connector": connector.provider, "mode": connector.mode, "token_present": bool(remote), "domain_match": domain_ok}
        else:
            raise ValidationFailed("Unknown method")
    except (BlockedDestination, ConnectorError) as exc:
        ok, evidence = False, {"error": str(exc)}
    verification.checked_at = utcnow()
    verification.evidence = evidence
    if ok:
        verification.status = "verified"
        verification.verified_at = utcnow()
        site.verified_at = utcnow()
        site.verification_method = verification.method
        site.status = "active"
        from datetime import timedelta

        for sched in db.execute(select(AutomationSchedule).where(AutomationSchedule.site_id == site.id,
                                                                 AutomationSchedule.enabled.is_(True))).scalars():
            if sched.next_run_at is None:
                sched.next_run_at = utcnow() + timedelta(minutes=sched.interval_minutes)
        audit.record(db, tenant_id=site.tenant_id, action="site.verified", actor_type="system", target_type="site", target_id=site.id,
                     site_id=site.id, data={"method": verification.method})
    else:
        verification.status = "pending"
    db.flush()
    return verification


def latest_verification(db: Session, site: Site) -> SiteVerification | None:
    return db.execute(select(SiteVerification).where(SiteVerification.site_id == site.id)
                      .order_by(SiteVerification.created_at.desc()).limit(1)).scalar_one_or_none()


def connectors_for(db: Session, site: Site) -> list[Connector]:
    return list(db.execute(select(Connector).where(Connector.site_id == site.id)).scalars())


_ = (asyncio, get_settings)


def push_fixture_token(db: Session, site: Site) -> bool:
    """Demo mode only: hand a pending 'connector' verification token to the local WordPress
    *fixture* (what a site owner would paste into the plugin settings). Never used for live connectors."""
    if not get_settings().demo_mode or get_settings().environment == "production":
        return False
    v = latest_verification(db, site)
    if v is None or v.method != "connector" or v.status == "verified":
        return False
    try:
        res = connector_svc.run(safe_fetch(site.base_url.rstrip("/") + "/__fixture/settings", method="POST",
                                           json_body={"verification_token": v.token}, max_redirects=0, timeout=5))
        return res.status_code == 200
    except (BlockedDestination, Exception):  # noqa: BLE001
        return False
