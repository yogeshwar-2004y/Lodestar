"""Connector lifecycle: context building (with secrets), capability sync, status checks."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from aseo.connectors.base import Capability, ConnectorContext
from aseo.connectors.registry import get_connector
from aseo.core.config import get_settings
from aseo.core.errors import ConnectorError, NotFound
from aseo.models import Connector, ConnectorCapability, ConnectorSecretRef, Site
from aseo.models.base import utcnow
from aseo.services import secrets as secret_store

SECRET_NAMES = {"wordpress": ["app_password"], "shopify": ["access_token"], "github": [], "gsc": ["refresh_token"]}


def run(coro):  # noqa: ANN001, ANN201 — run async connector code from sync services/workers
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(1) as ex:
        return ex.submit(asyncio.run, coro).result()


def build_context(db: Session, site: Site, connector: Connector | None) -> ConnectorContext:
    settings = get_settings()
    if connector is None:
        return ConnectorContext(str(site.id), site.base_url, site.domain, None, "public", "live", {})
    if connector.mode == "fixture" and settings.environment == "production":
        raise ConnectorError("Fixture connectors are not allowed in production.", code="fixture_in_production")
    secrets = {}
    for name in SECRET_NAMES.get(connector.provider, []):
        value = secret_store.get_secret(db, connector.id, name)
        if value is not None:
            secrets[name] = value
    return ConnectorContext(str(site.id), site.base_url, site.domain, str(connector.id), connector.provider, connector.mode,
                            dict(connector.config), secrets)


def write_connector_for(db: Session, site: Site) -> Connector | None:
    """The connector that performs website writes for this site (not GSC)."""
    return db.execute(
        select(Connector).where(Connector.site_id == site.id, Connector.provider.in_(["wordpress", "shopify", "github"]))
        .order_by(Connector.created_at.desc())
    ).scalars().first()


def capability_for(db: Session, connector: Connector | None, action_type: str) -> ConnectorCapability | None:
    if connector is None:
        return None
    return db.execute(
        select(ConnectorCapability).where(ConnectorCapability.connector_id == connector.id, ConnectorCapability.action_type == action_type)
    ).scalar_one_or_none()


def sync_capabilities(db: Session, connector: Connector, caps: list[Capability]) -> None:
    existing = {c.action_type: c for c in db.execute(select(ConnectorCapability).where(ConnectorCapability.connector_id == connector.id)).scalars()}
    for cap in caps:
        row = existing.get(cap.action_type)
        if row is None:
            row = ConnectorCapability(tenant_id=connector.tenant_id, connector_id=connector.id, action_type=cap.action_type)
            db.add(row)
        row.supported = cap.supported
        row.write_mode = cap.write_mode
        row.rollback_supported = cap.rollback_supported
        row.preconditions = cap.preconditions
        row.permissions = cap.permissions
        row.notes = cap.notes
    db.flush()


def connect(db: Session, *, site: Site, provider: str, config: dict[str, Any], secrets: dict[str, str], mode: str = "live") -> Connector:
    settings = get_settings()
    if mode == "fixture" and (settings.environment == "production" or not settings.demo_mode):
        raise ConnectorError("Fixture connectors are only available in demo mode.", code="fixture_not_allowed")
    connector = db.execute(select(Connector).where(Connector.site_id == site.id, Connector.provider == provider)).scalar_one_or_none()
    if connector is None:
        connector = Connector(tenant_id=site.tenant_id, site_id=site.id, provider=provider)
        db.add(connector)
    connector.config = {k: v for k, v in config.items() if v is not None}
    connector.mode = mode
    connector.status = "pending"
    db.flush()
    for name, value in secrets.items():
        if value:
            secret_store.put_secret(db, tenant_id=site.tenant_id, connector_id=connector.id, name=name, value=value)
    return check(db, site, connector)


def check(db: Session, site: Site, connector: Connector) -> Connector:
    impl = get_connector(connector.provider)
    ctx = build_context(db, site, connector)
    try:
        info = run(impl.verify_ownership(ctx))
        caps = run(impl.capabilities(ctx))
        sync_capabilities(db, connector, caps)
        connector.status = "connected"
        connector.last_error = None
        connector.config = {**connector.config, "remote": {k: v for k, v in info.items() if k != "verification_token"}}
    except ConnectorError as exc:
        connector.status = "error"
        connector.last_error = exc.message
    connector.last_checked_at = utcnow()
    db.flush()
    return connector


def disconnect(db: Session, connector: Connector) -> None:
    secret_store.revoke_secrets(db, connector.id)
    connector.status = "disconnected"


def secret_status(db: Session, connector_id: uuid.UUID) -> list[dict[str, Any]]:
    rows = db.execute(select(ConnectorSecretRef).where(ConnectorSecretRef.connector_id == connector_id)).scalars()
    return [{"name": r.name, "backend": r.backend, "fingerprint": r.fingerprint, "rotated_at": r.rotated_at,
             "revoked": r.revoked_at is not None, "created_at": r.created_at} for r in rows]


def get_site_connector(db: Session, connector_id: uuid.UUID) -> Connector:
    c = db.get(Connector, connector_id)
    if c is None:
        raise NotFound("Connector not found")
    return c
