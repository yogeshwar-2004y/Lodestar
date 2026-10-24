"""Plans, quotas, append-only AI credit ledger and usage metering.

Every expensive operation (1) checks the available budget *before* it is scheduled and
(2) charges exactly once using an idempotency key (unique per tenant in the ledger)."""

from __future__ import annotations

import math
import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from aseo.core.errors import BudgetExceeded, Forbidden
from aseo.models import CreditLedger, Plan, Site, Subscription, UsageRecord
from aseo.models.base import utcnow

# Credit pricing (editable here; surfaced in /usage).
CREDITS_PER_CRAWL_PAGES = 10  # 1 credit per 10 pages
TOKENS_PER_CREDIT = 1000  # AI: 1 credit per 1k tokens (input+output), min 1 per call

DEFAULT_PLANS: list[dict[str, Any]] = [
    {"key": "starter", "name": "Starter", "monthly_price_cents": 4900, "included_credits": 2000, "max_sites": 3,
     "max_pages_per_crawl": 500, "max_workspaces": 1, "sort": 1,
     "features": ["Technical audits", "Approval workflow", "WordPress & Shopify connectors", "Search Console"]},
    {"key": "growth", "name": "Growth", "monthly_price_cents": 14900, "included_credits": 10000, "max_sites": 10,
     "max_pages_per_crawl": 5000, "max_workspaces": 3, "sort": 2,
     "features": ["Everything in Starter", "GitHub PR workflow", "Content Studio", "Autopilot for whitelisted fixes"]},
    {"key": "agency", "name": "Agency", "monthly_price_cents": 39900, "included_credits": 40000, "max_sites": 50,
     "max_pages_per_crawl": 10000, "max_workspaces": 50, "sort": 3,
     "features": ["Everything in Growth", "Client workspaces", "Branded reports", "Client roles"]},
]


def crawl_credit_cost(max_pages: int) -> int:
    return max(1, math.ceil(max_pages / CREDITS_PER_CRAWL_PAGES))


def ai_credit_cost(input_tokens: int, output_tokens: int) -> int:
    total = input_tokens + output_tokens
    return 0 if total == 0 else max(1, math.ceil(total / TOKENS_PER_CREDIT))


def balance(db: Session, tenant_id: uuid.UUID) -> int:
    value = db.execute(
        select(CreditLedger.balance_after).where(CreditLedger.tenant_id == tenant_id).order_by(CreditLedger.seq.desc()).limit(1)
    ).scalar_one_or_none()
    return int(value or 0)


def _lock(db: Session, tenant_id: uuid.UUID) -> None:
    db.execute(text("select pg_advisory_xact_lock(hashtext(:k))"), {"k": f"ledger:{tenant_id}"})


def post(
    db: Session,
    tenant_id: uuid.UUID,
    delta: int,
    *,
    reason: str,
    idempotency_key: str,
    ref_type: str | None = None,
    ref_id: str | None = None,
    allow_negative: bool = False,
    meta: dict[str, Any] | None = None,
) -> CreditLedger:
    """Append a ledger entry exactly once per (tenant, idempotency_key)."""
    _lock(db, tenant_id)
    existing = db.execute(
        select(CreditLedger).where(CreditLedger.tenant_id == tenant_id, CreditLedger.idempotency_key == idempotency_key)
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    current = balance(db, tenant_id)
    new_balance = current + delta
    if new_balance < 0 and not allow_negative:
        raise BudgetExceeded(
            f"Not enough AI credits: need {-delta}, have {current}.",
            details={"required": -delta, "available": current},
        )
    entry = CreditLedger(
        tenant_id=tenant_id, delta=delta, balance_after=new_balance, reason=reason, idempotency_key=idempotency_key,
        ref_type=ref_type, ref_id=ref_id, meta=meta or {},
    )
    db.add(entry)
    db.flush()
    return entry


def check_budget(db: Session, tenant_id: uuid.UUID, credits: int) -> None:
    available = balance(db, tenant_id)
    if available < credits:
        raise BudgetExceeded(
            f"This operation needs {credits} credits but only {available} are available.",
            details={"required": credits, "available": available},
        )


def record_usage(db: Session, tenant_id: uuid.UUID, metric: str, quantity: int, ref_type: str | None = None, ref_id: str | None = None) -> None:
    if quantity <= 0:
        return
    db.add(UsageRecord(tenant_id=tenant_id, metric=metric, quantity=quantity, period=utcnow().strftime("%Y-%m"),
                       ref_type=ref_type, ref_id=ref_id))


def subscription(db: Session, tenant_id: uuid.UUID) -> tuple[Subscription | None, Plan | None]:
    sub = db.execute(select(Subscription).where(Subscription.tenant_id == tenant_id)).scalar_one_or_none()
    plan = db.get(Plan, sub.plan_id) if sub else None
    return sub, plan


def ensure_plans(db: Session) -> None:
    for spec in DEFAULT_PLANS:
        if db.execute(select(Plan).where(Plan.key == spec["key"])).scalar_one_or_none() is None:
            db.add(Plan(**spec))
    db.flush()


def start_subscription(db: Session, tenant_id: uuid.UUID, plan_key: str = "starter", provider: str = "test") -> Subscription:
    ensure_plans(db)
    plan = db.execute(select(Plan).where(Plan.key == plan_key)).scalar_one()
    now = utcnow()
    sub = Subscription(tenant_id=tenant_id, plan_id=plan.id, status="trialing", provider=provider,
                       current_period_start=now, current_period_end=now + timedelta(days=30))
    db.add(sub)
    db.flush()
    post(db, tenant_id, plan.included_credits, reason="grant", idempotency_key=f"grant:{tenant_id}:{now:%Y-%m}",
         ref_type="plan", ref_id=plan.key)
    return sub


def enforce_site_quota(db: Session, tenant_id: uuid.UUID) -> None:
    _, plan = subscription(db, tenant_id)
    if plan is None:
        return
    count = db.execute(select(func.count()).select_from(Site).where(Site.tenant_id == tenant_id)).scalar_one()
    if count >= plan.max_sites:
        raise Forbidden(f"Your {plan.name} plan allows {plan.max_sites} sites.", code="quota_exceeded")


def max_pages_allowed(db: Session, tenant_id: uuid.UUID) -> int:
    _, plan = subscription(db, tenant_id)
    return plan.max_pages_per_crawl if plan else 100


def reconcile(db: Session, tenant_id: uuid.UUID) -> dict[str, Any]:
    """Verify the ledger is internally consistent (each balance = previous + delta)."""
    rows = db.execute(select(CreditLedger).where(CreditLedger.tenant_id == tenant_id).order_by(CreditLedger.seq)).scalars()
    running, ok, n = 0, True, 0
    for r in rows:
        running += r.delta
        n += 1
        if r.balance_after != running:
            ok = False
            break
    return {"consistent": ok, "entries": n, "balance": running}
