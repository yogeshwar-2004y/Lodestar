"""Payment provider abstraction.

* ``test`` provider — local test mode: plan changes apply immediately and a signed test
  webhook is produced/verified exactly like a real provider (HMAC-SHA256 + timestamp,
  5-minute tolerance, replay-protected via the event inbox).
* ``stripe`` provider — Checkout Session creation + ``Stripe-Signature`` verification
  (requires STRIPE_SECRET_KEY / STRIPE_WEBHOOK_SECRET; see docs/setup/billing.md).
"""

from __future__ import annotations

import hmac
import json
import time
import uuid
from hashlib import sha256
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from aseo.core.config import get_settings
from aseo.core.errors import Conflict, NotFound, Unauthorized, ValidationFailed
from aseo.models import EventInbox, Plan, Subscription, Tenant
from aseo.models.base import utcnow
from aseo.services import audit, billing

TOLERANCE_SECONDS = 300


def sign(secret: str, payload: bytes, ts: int | None = None) -> str:
    ts = ts or int(time.time())
    mac = hmac.new(secret.encode(), f"{ts}.".encode() + payload, sha256).hexdigest()
    return f"t={ts},v1={mac}"


def verify_signature(secret: str, payload: bytes, header: str, now: int | None = None) -> None:
    try:
        parts = dict(p.split("=", 1) for p in header.split(","))
        ts = int(parts["t"])
        sig = parts["v1"]
    except Exception as exc:  # noqa: BLE001
        raise Unauthorized("Malformed signature header", code="bad_signature") from exc
    if abs((now or int(time.time())) - ts) > TOLERANCE_SECONDS:
        raise Unauthorized("Signature timestamp outside tolerance", code="stale_signature")
    expected = hmac.new(secret.encode(), f"{ts}.".encode() + payload, sha256).hexdigest()
    if not hmac.compare_digest(expected, sig):
        raise Unauthorized("Invalid signature", code="bad_signature")


def create_checkout(db: Session, tenant: Tenant, plan_key: str, actor: Any) -> dict[str, Any]:
    plan = db.execute(select(Plan).where(Plan.key == plan_key, Plan.is_active.is_(True))).scalar_one_or_none()
    if plan is None:
        raise NotFound("Plan not found")
    s = get_settings()
    if s.billing_provider == "stripe":  # pragma: no cover - requires credentials
        if not s.stripe_secret_key or not plan.provider_price_ref:
            raise ValidationFailed("Stripe is not configured for this plan (set STRIPE_SECRET_KEY and plans.provider_price_ref).")
        r = httpx.post("https://api.stripe.com/v1/checkout/sessions", auth=(s.stripe_secret_key, ""), timeout=20, data={
            "mode": "subscription", "line_items[0][price]": plan.provider_price_ref, "line_items[0][quantity]": "1",
            "client_reference_id": str(tenant.id), "success_url": f"{s.public_web_url}/app/billing?status=success",
            "cancel_url": f"{s.public_web_url}/app/billing?status=cancelled"})
        r.raise_for_status()
        return {"provider": "stripe", "checkout_url": r.json()["url"]}
    # test mode: emit a signed event and process it through the same webhook path
    event = {"id": f"evt_test_{uuid.uuid4().hex}", "type": "subscription.updated", "data": {"tenant_id": str(tenant.id), "plan_key": plan.key}}
    payload = json.dumps(event).encode()
    handle_webhook(db, "billing", payload, sign(s.test_billing_webhook_secret, payload))
    audit.record(db, tenant_id=tenant.id, action="billing.plan_changed", actor_id=actor.id, actor_label=actor.label,
                 target_type="subscription", data={"plan": plan.key, "provider": "test"})
    return {"provider": "test", "status": "active", "plan": plan.key, "note": "Test mode — no payment was taken."}


def handle_webhook(db: Session, provider: str, payload: bytes, signature: str | None) -> dict[str, Any]:
    s = get_settings()
    secret = s.stripe_webhook_secret if s.billing_provider == "stripe" else s.test_billing_webhook_secret
    if not secret or not signature:
        raise Unauthorized("Missing webhook signature", code="bad_signature")
    verify_signature(secret, payload, signature)
    event = json.loads(payload)
    tenant_id = event.get("data", {}).get("tenant_id") or event.get("data", {}).get("object", {}).get("client_reference_id")
    inbox = EventInbox(tenant_id=uuid.UUID(tenant_id) if tenant_id else None, provider=provider, event_id=str(event["id"]),
                       event_type=event.get("type", "unknown"), payload={"type": event.get("type")})
    try:
        with db.begin_nested():
            db.add(inbox)
            db.flush()
    except IntegrityError as exc:
        raise Conflict("Duplicate webhook event (replay ignored).", code="webhook_replay") from exc
    if event.get("type") in ("subscription.updated", "checkout.session.completed") and tenant_id:
        from aseo.core.db import set_session_tenant

        set_session_tenant(db, uuid.UUID(tenant_id))
        plan_key = event["data"].get("plan_key")
        plan = db.execute(select(Plan).where(Plan.key == plan_key)).scalar_one_or_none() if plan_key else None
        sub = db.execute(select(Subscription).where(Subscription.tenant_id == uuid.UUID(tenant_id))).scalar_one_or_none()
        if plan and sub:
            upgrade = plan.included_credits
            sub.plan_id, sub.status, sub.provider = plan.id, "active", s.billing_provider
            billing.post(db, sub.tenant_id, upgrade, reason="grant", idempotency_key=f"grant:{sub.tenant_id}:{event['id']}",
                         ref_type="plan", ref_id=plan.key)
    inbox.status, inbox.processed_at = "processed", utcnow()
    return {"received": True}
