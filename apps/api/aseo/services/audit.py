"""Append-only, hash-chained audit log."""

from __future__ import annotations

import json
import uuid
from datetime import UTC
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from aseo.core.logging import request_id_ctx
from aseo.core.security import sha256_hex
from aseo.models import AuditEvent
from aseo.models.base import utcnow

_SENSITIVE = ("secret", "token", "password", "authorization", "api_key", "apikey", "cookie", "private_key", "code_verifier")


def sanitize(data: Any) -> Any:
    """Remove secret-like keys from audit payloads (defence in depth)."""
    if isinstance(data, dict):
        return {
            k: ("[REDACTED]" if any(s in k.lower() for s in _SENSITIVE) else sanitize(v)) for k, v in data.items()
        }
    if isinstance(data, list):
        return [sanitize(v) for v in data]
    return data


def record(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    action: str,
    actor_type: str = "user",
    actor_id: str | uuid.UUID | None = None,
    actor_label: str | None = None,
    target_type: str | None = None,
    target_id: str | uuid.UUID | None = None,
    site_id: uuid.UUID | None = None,
    data: dict[str, Any] | None = None,
    ip: str | None = None,
) -> AuditEvent:
    # Serialize chain extension per tenant.
    db.execute(text("select pg_advisory_xact_lock(hashtext(:k))"), {"k": f"audit:{tenant_id}"})
    prev = db.execute(
        select(AuditEvent.hash).where(AuditEvent.tenant_id == tenant_id).order_by(AuditEvent.created_at.desc()).limit(1)
    ).scalar_one_or_none()
    created = utcnow()
    clean = sanitize(data or {})
    body = {
        "tenant_id": str(tenant_id),
        "action": action,
        "actor": [actor_type, str(actor_id) if actor_id else None],
        "target": [target_type, str(target_id) if target_id else None],
        "site_id": str(site_id) if site_id else None,
        "data": clean,
        "created_at": created.astimezone(UTC).isoformat(),
        "prev": prev,
    }
    digest = sha256_hex(json.dumps(body, sort_keys=True, default=str))
    event = AuditEvent(
        tenant_id=tenant_id,
        created_at=created,
        actor_type=actor_type,
        actor_id=str(actor_id) if actor_id else None,
        actor_label=actor_label,
        action=action,
        target_type=target_type,
        target_id=str(target_id) if target_id else None,
        site_id=site_id,
        data=clean,
        request_id=request_id_ctx.get(),
        ip=ip,
        prev_hash=prev,
        hash=digest,
    )
    db.add(event)
    db.flush()
    return event


def verify_chain(db: Session, tenant_id: uuid.UUID) -> dict[str, Any]:
    rows = db.execute(
        select(AuditEvent).where(AuditEvent.tenant_id == tenant_id).order_by(AuditEvent.created_at.asc())
    ).scalars()
    prev = None
    count = 0
    for ev in rows:
        body = {
            "tenant_id": str(ev.tenant_id),
            "action": ev.action,
            "actor": [ev.actor_type, ev.actor_id],
            "target": [ev.target_type, ev.target_id],
            "site_id": str(ev.site_id) if ev.site_id else None,
            "data": ev.data,
            "created_at": ev.created_at.astimezone(UTC).isoformat(),
            "prev": prev,
        }
        if ev.prev_hash != prev or sha256_hex(json.dumps(body, sort_keys=True, default=str)) != ev.hash:
            return {"valid": False, "broken_at": str(ev.id), "checked": count}
        prev = ev.hash
        count += 1
    return {"valid": True, "checked": count}
