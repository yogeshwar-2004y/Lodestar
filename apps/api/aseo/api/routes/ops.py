from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy import func, select

from aseo.agents import agents
from aseo.api.deps import Ctx, get_ctx, paginate, require
from aseo.api.schemas import (
    AnnotationOut,
    AutomationPolicyIn,
    ContentDraftIn,
    ContentReviewIn,
    Page_,
    ReportIn,
    ScheduleIn,
)
from aseo.core.config import get_settings
from aseo.core.errors import Conflict, NotFound
from aseo.models import (
    AgentRun,
    AuditEvent,
    AutomationSchedule,
    ClientWorkspace,
    ContentDraft,
    CreditLedger,
    DataSourceSync,
    KeywordCluster,
    KeywordQuery,
    MeasurementAnnotation,
    Notification,
    Plan,
    Report,
    SearchMetric,
    Site,
    UsageRecord,
)
from aseo.models.base import utcnow
from aseo.services import audit, billing, reports
from aseo.services.changes import ensure_policy

router = APIRouter(tags=["operations"])


@router.get("/meta", summary="Public product metadata (demo mode, AI mode)")
def meta() -> dict[str, Any]:
    from aseo.ai.gateway import Gateway

    s = get_settings()
    gw = Gateway()
    return {"product_name": s.product_name, "environment": s.environment, "demo_mode": s.demo_mode, "ai_mode": gw.mode,
            "ai_model": s.ai_model if gw.mode == "llm" else None, "ai_note": gw.unavailable_reason,
            "billing_provider": s.billing_provider,
            "integrations": {"shopify": bool(s.shopify_api_key), "github": bool(s.github_app_id), "gsc": bool(s.google_client_id)}}


# ------------------------------------------------------------------ analytics


@router.get("/sites/{site_id}/performance", summary="Search Console performance with annotations and caveats")
def performance(site_id: uuid.UUID, days: int = 90, ctx: Ctx = Depends(require("analytics:read"))) -> dict[str, Any]:
    site = ctx.site(site_id, "analytics:read")
    since = utcnow().date() - timedelta(days=days)
    rows = ctx.db.execute(select(SearchMetric.date, func.sum(SearchMetric.clicks), func.sum(SearchMetric.impressions),
                                 func.avg(SearchMetric.position), func.min(SearchMetric.source))
                          .where(SearchMetric.site_id == site.id, SearchMetric.date >= since, SearchMetric.query == "")
                          .group_by(SearchMetric.date).order_by(SearchMetric.date)).all()
    series = [{"date": d.isoformat(), "clicks": int(c or 0), "impressions": int(i or 0), "ctr": round((c or 0) / i, 4) if i else 0,
               "position": round(float(p), 2) if p else None} for d, c, i, p, _ in rows]
    sources = {s for *_, s in rows}
    sync = ctx.db.execute(select(DataSourceSync).where(DataSourceSync.site_id == site.id, DataSourceSync.source == "gsc")
                          .order_by(DataSourceSync.created_at.desc()).limit(1)).scalar_one_or_none()
    ann = ctx.db.execute(select(MeasurementAnnotation).where(MeasurementAnnotation.site_id == site.id, MeasurementAnnotation.date >= since)
                         .order_by(MeasurementAnnotation.date)).scalars()
    top_pages = ctx.db.execute(select(SearchMetric.page, func.sum(SearchMetric.clicks), func.sum(SearchMetric.impressions))
                               .where(SearchMetric.site_id == site.id, SearchMetric.date >= since, SearchMetric.page != "",
                                      SearchMetric.query == "").group_by(SearchMetric.page)
                               .order_by(func.sum(SearchMetric.clicks).desc()).limit(10)).all()
    return {
        "connected": sync is not None,
        "source": "demo_fixture" if "demo_fixture" in sources else ("gsc" if sources else None),
        "is_demo_data": "demo_fixture" in sources,
        "data_through": sync.data_through.isoformat() if sync and sync.data_through else None,
        "series": series,
        "totals": {"clicks": sum(x["clicks"] for x in series), "impressions": sum(x["impressions"] for x in series)},
        "top_pages": [{"page": p, "clicks": int(c), "impressions": int(i)} for p, c, i in top_pages],
        "annotations": [AnnotationOut.model_validate(a).model_dump(mode="json") for a in ann],
        "caveats": [
            "Search Console data is typically delayed 2-3 days and the latest days may be incomplete.",
            "Search Console filters some queries for privacy and does not report every impression.",
            "Changes in clicks after a fix may be caused by seasonality, algorithm updates or other site changes.",
            "Technical fix verification is tracked separately from search outcomes.",
        ],
    }


@router.get("/sites/{site_id}/keywords", summary="Query groups and opportunities with data-source provenance")
def keywords(site_id: uuid.UUID, ctx: Ctx = Depends(require("analytics:read"))) -> dict[str, Any]:
    site = ctx.site(site_id, "analytics:read")
    clusters = ctx.db.execute(select(KeywordCluster).where(KeywordCluster.site_id == site.id).order_by(KeywordCluster.clicks.desc())).scalars().all()
    queries = ctx.db.execute(select(KeywordQuery).where(KeywordQuery.site_id == site.id).order_by(KeywordQuery.impressions.desc()).limit(200)).scalars().all()
    return {
        "clusters": [{"id": str(c.id), "name": c.name, "intent": c.intent, "queries": c.queries_count, "clicks": c.clicks,
                      "impressions": c.impressions, "opportunity_score": c.opportunity_score, "source": c.source} for c in clusters],
        "queries": [{"id": str(q.id), "query": q.query, "page": q.page_url, "clicks": q.clicks, "impressions": q.impressions, "ctr": q.ctr,
                     "position": q.position, "search_volume": q.search_volume, "source": q.source,
                     "cluster_id": str(q.cluster_id) if q.cluster_id else None} for q in queries],
        "providers": {"gsc": "Google Search Console (your own site's queries)",
                      "paid": "No paid keyword provider configured — search volume is not shown rather than estimated."},
    }


# ------------------------------------------------------------------ automations


@router.get("/sites/{site_id}/automations")
def automations(site_id: uuid.UUID, ctx: Ctx = Depends(require("automation:read"))) -> dict[str, Any]:
    site = ctx.site(site_id, "automation:read")
    pol = ensure_policy(ctx.db, site)
    schedules = ctx.db.execute(select(AutomationSchedule).where(AutomationSchedule.site_id == site.id)).scalars()
    return {
        "policy": {"mode": pol.mode, "auto_actions": pol.auto_actions, "path_scope": pol.path_scope, "paused": pol.paused,
                   "max_auto_changes_per_day": pol.max_auto_changes_per_day, "max_risk_score": pol.max_risk_score,
                   "updated_at": pol.updated_at.isoformat()},
        "kill_switch": ctx.tenant.kill_switch,
        "schedules": [{"id": str(s.id), "kind": s.kind, "interval_minutes": s.interval_minutes, "enabled": s.enabled,
                       "next_run_at": s.next_run_at.isoformat() if s.next_run_at else None,
                       "last_run_at": s.last_run_at.isoformat() if s.last_run_at else None} for s in schedules],
        "event_triggers": [
            {"event": "connector webhook: content updated (WordPress/Shopify)", "action": "re-crawl affected URL", "enabled": True},
            {"event": "GitHub deployment_status=success", "action": "verify pending pull-request changes", "enabled": True},
            {"event": "crawl completed", "action": "Audit → Strategy → Execution proposals", "enabled": True},
        ],
        "auto_eligible_actions": ["meta_description", "title"],
        "always_review": ["internal_link", "structured_data", "content_publish"],
        "restricted": ["canonical", "robots", "redirect", "delete"],
    }


@router.put("/sites/{site_id}/automations/policy", summary="Set Observe / Assist / Autopilot policy")
def set_policy(site_id: uuid.UUID, body: AutomationPolicyIn, ctx: Ctx = Depends(require("automation:manage"))) -> dict[str, Any]:
    site = ctx.site(site_id, "automation:manage")
    pol = ensure_policy(ctx.db, site)
    if body.mode == "autopilot" and not site.verified_at:
        raise Conflict("Verify site ownership before enabling Autopilot.", code="site_not_verified")
    before = {"mode": pol.mode, "auto_actions": pol.auto_actions, "paused": pol.paused}
    for k, v in body.model_dump().items():
        setattr(pol, k, v)
    pol.updated_by = ctx.user.id
    audit.record(ctx.db, tenant_id=ctx.tenant.id, action="automation.policy_updated", actor_id=ctx.user.id, actor_label=ctx.user.email,
                 target_type="site", target_id=site.id, site_id=site.id, data={"before": before, "after": body.model_dump()})
    return automations(site_id, ctx)


@router.put("/sites/{site_id}/automations/schedule")
def set_schedule(site_id: uuid.UUID, body: ScheduleIn, ctx: Ctx = Depends(require("automation:manage"))) -> dict[str, Any]:
    site = ctx.site(site_id, "automation:manage")
    s = ctx.db.execute(select(AutomationSchedule).where(AutomationSchedule.site_id == site.id, AutomationSchedule.kind == body.kind)).scalar_one_or_none()
    if s is None:
        s = AutomationSchedule(tenant_id=ctx.tenant.id, site_id=site.id, kind=body.kind)
        ctx.db.add(s)
    s.interval_minutes, s.enabled = body.interval_minutes, body.enabled
    s.next_run_at = utcnow() + timedelta(minutes=body.interval_minutes) if body.enabled else None
    audit.record(ctx.db, tenant_id=ctx.tenant.id, action="automation.schedule_updated", actor_id=ctx.user.id, actor_label=ctx.user.email,
                 target_type="site", target_id=site.id, site_id=site.id, data=body.model_dump())
    return automations(site_id, ctx)


# ------------------------------------------------------------------ usage & billing


@router.get("/usage", summary="Plan, credits, quotas and ledger")
def usage(ctx: Ctx = Depends(require("usage:read"))) -> dict[str, Any]:
    sub, plan = billing.subscription(ctx.db, ctx.tenant.id)
    period = utcnow().strftime("%Y-%m")
    metrics = dict(ctx.db.execute(select(UsageRecord.metric, func.sum(UsageRecord.quantity)).where(
        UsageRecord.tenant_id == ctx.tenant.id, UsageRecord.period == period).group_by(UsageRecord.metric)).all())
    ledger = ctx.db.execute(select(CreditLedger).where(CreditLedger.tenant_id == ctx.tenant.id).order_by(CreditLedger.seq.desc()).limit(50)).scalars()
    sites = ctx.db.execute(select(func.count()).select_from(Site).where(Site.tenant_id == ctx.tenant.id)).scalar_one()
    ai_cost = ctx.db.execute(select(func.coalesce(func.sum(AgentRun.cost_usd), 0)).where(AgentRun.tenant_id == ctx.tenant.id)).scalar_one()
    return {
        "plan": {"key": plan.key, "name": plan.name, "monthly_price_cents": plan.monthly_price_cents, "currency": plan.currency,
                 "included_credits": plan.included_credits, "max_sites": plan.max_sites, "max_pages_per_crawl": plan.max_pages_per_crawl,
                 "features": plan.features} if plan else None,
        "subscription": {"status": sub.status, "provider": sub.provider,
                         "current_period_end": sub.current_period_end.isoformat() if sub and sub.current_period_end else None} if sub else None,
        "credits": {"balance": billing.balance(ctx.db, ctx.tenant.id), "pricing": {"crawl": f"1 credit per {billing.CREDITS_PER_CRAWL_PAGES} pages",
                                                                                   "ai": f"1 credit per {billing.TOKENS_PER_CREDIT} tokens"}},
        "quotas": {"sites_used": sites, "sites_limit": plan.max_sites if plan else None},
        "period": period,
        "usage": {k: int(v) for k, v in metrics.items()},
        "ai_cost_usd_to_date": float(ai_cost or 0),
        "ledger": [{"seq": e.seq, "delta": e.delta, "balance_after": e.balance_after, "reason": e.reason, "ref_type": e.ref_type,
                    "ref_id": e.ref_id, "created_at": e.created_at.isoformat()} for e in ledger],
        "reconciliation": billing.reconcile(ctx.db, ctx.tenant.id),
        "invoices": [] if get_settings().billing_provider == "test" else None,
        "billing_provider": get_settings().billing_provider,
    }


@router.get("/billing/plans")
def plans(ctx: Ctx = Depends(get_ctx)) -> list[dict[str, Any]]:
    rows = ctx.db.execute(select(Plan).where(Plan.is_active.is_(True)).order_by(Plan.sort)).scalars()
    return [{"key": p.key, "name": p.name, "monthly_price_cents": p.monthly_price_cents, "currency": p.currency,
             "included_credits": p.included_credits, "max_sites": p.max_sites, "max_pages_per_crawl": p.max_pages_per_crawl,
             "max_workspaces": p.max_workspaces, "features": p.features} for p in rows]


@router.post("/billing/checkout", summary="Change plan (test-mode payment provider)")
def checkout(plan_key: str, ctx: Ctx = Depends(require("billing:manage"))) -> dict[str, Any]:
    from aseo.services import payments

    return payments.create_checkout(ctx.db, ctx.tenant, plan_key, ctx.actor)


# ------------------------------------------------------------------ reports


@router.get("/reports")
def list_reports(ctx: Ctx = Depends(require("report:read"))) -> list[dict[str, Any]]:
    q = select(Report, Site).join(Site, Site.id == Report.site_id).where(ctx.site_filter()).order_by(Report.created_at.desc()).limit(50)
    return [{"id": str(r.id), "title": r.title, "site_id": str(r.site_id), "site": s.name, "status": r.status,
             "period_start": r.period_start.isoformat() if r.period_start else None,
             "period_end": r.period_end.isoformat() if r.period_end else None, "created_at": r.created_at.isoformat(),
             "download_url": f"/api/v1/reports/{r.id}/pdf" if r.status == "ready" else None} for r, s in ctx.db.execute(q).all()]


@router.post("/reports", status_code=201, summary="Generate a branded PDF report")
def create_report(body: ReportIn, ctx: Ctx = Depends(require("report:create"))) -> dict[str, Any]:
    site = ctx.site(body.site_id, "report:create")
    ws = ctx.db.get(ClientWorkspace, site.workspace_id) if site.workspace_id else None
    r = reports.generate(ctx.db, ctx.tenant, site, ws, title=body.title, period_days=body.period_days, created_by=ctx.user.id)
    return {"id": str(r.id), "status": r.status, "download_url": f"/api/v1/reports/{r.id}/pdf"}


@router.get("/reports/{report_id}/pdf")
def download_report(report_id: uuid.UUID, ctx: Ctx = Depends(require("report:read"))) -> Response:
    r = ctx.db.get(Report, report_id)
    if r is None:
        raise NotFound("Report not found")
    ctx.site(r.site_id, "report:read")
    data = reports.load_pdf(r)
    if data is None:
        raise NotFound("Report file missing")
    return Response(data, media_type="application/pdf", headers={"content-disposition": f'inline; filename="report-{r.id}.pdf"'})


# ------------------------------------------------------------------ audit & notifications


@router.get("/audit-events", response_model=Page_[dict[str, Any]])
def audit_events(site_id: uuid.UUID | None = None, target_id: str | None = None, cursor: str | None = None, limit: int = 50,
                 ctx: Ctx = Depends(get_ctx)) -> Page_[dict[str, Any]]:
    if target_id or site_id:
        if site_id:
            ctx.site(site_id)
    else:
        ctx.require("audit:read")
    q = select(AuditEvent).where(AuditEvent.tenant_id == ctx.tenant.id)
    if site_id:
        q = q.where(AuditEvent.site_id == site_id)
    if target_id:
        q = q.where(AuditEvent.target_id == target_id)
    rows, nxt = paginate(ctx.db, q, AuditEvent, cursor, limit)
    return Page_[dict[str, Any]](items=[{"id": str(a.id), "created_at": a.created_at.isoformat(), "actor_type": a.actor_type,
                                         "actor": a.actor_label, "action": a.action, "target_type": a.target_type, "target_id": a.target_id,
                                         "site_id": str(a.site_id) if a.site_id else None, "data": a.data, "hash": a.hash,
                                         "prev_hash": a.prev_hash} for a in rows], next_cursor=nxt)


@router.get("/audit-events/verify", summary="Verify the tamper-evident hash chain")
def verify_audit(ctx: Ctx = Depends(require("audit:read"))) -> dict[str, Any]:
    return audit.verify_chain(ctx.db, ctx.tenant.id)


@router.get("/notifications")
def list_notifications(ctx: Ctx = Depends(get_ctx)) -> dict[str, Any]:
    rows = ctx.db.execute(select(Notification).where(Notification.tenant_id == ctx.tenant.id,
                                                     (Notification.user_id.is_(None)) | (Notification.user_id == ctx.user.id))
                          .order_by(Notification.created_at.desc()).limit(30)).scalars().all()
    return {"unread": sum(1 for n in rows if n.read_at is None),
            "items": [{"id": str(n.id), "kind": n.kind, "severity": n.severity, "title": n.title, "body": n.body, "link": n.link,
                       "read": n.read_at is not None, "created_at": n.created_at.isoformat()} for n in rows]}


@router.post("/notifications/read", status_code=204, response_class=Response)
def mark_read(ctx: Ctx = Depends(get_ctx)) -> Response:
    for n in ctx.db.execute(select(Notification).where(Notification.tenant_id == ctx.tenant.id, Notification.read_at.is_(None))).scalars():
        n.read_at = utcnow()
    return Response(status_code=204)


# ------------------------------------------------------------------ content studio


@router.post("/sites/{site_id}/content/drafts", status_code=201, summary="Generate a brief + draft (never auto-published)")
def create_draft(site_id: uuid.UUID, body: ContentDraftIn, ctx: Ctx = Depends(get_ctx)) -> dict[str, Any]:
    site = ctx.site(site_id, "content:write")
    run, brief = agents.draft_content(ctx.db, site, target_query=body.target_query, notes=body.notes)
    d = ContentDraft(tenant_id=ctx.tenant.id, site_id=site.id, kind="article", title=brief.title, target_query=body.target_query,
                     brief=brief.model_dump(), body=brief.draft_markdown, status="draft", ai_generated=run.provider != "deterministic",
                     agent_run_id=run.id, created_by=ctx.user.id)
    ctx.db.add(d)
    ctx.db.flush()
    audit.record(ctx.db, tenant_id=ctx.tenant.id, action="content.draft_created", actor_id=ctx.user.id, actor_label=ctx.user.email,
                 target_type="content_draft", target_id=d.id, site_id=site.id, data={"provider": run.provider})
    return _draft_out(d)


def _draft_out(d: ContentDraft) -> dict[str, Any]:
    return {"id": str(d.id), "site_id": str(d.site_id), "title": d.title, "target_query": d.target_query, "brief": d.brief, "body": d.body,
            "status": d.status, "review_notes": d.review_notes, "ai_generated": d.ai_generated,
            "editorial_approved_at": d.editorial_approved_at.isoformat() if d.editorial_approved_at else None,
            "created_at": d.created_at.isoformat(), "updated_at": d.updated_at.isoformat(),
            "publishing": "Publishing is manual in V1: copy the approved draft into your CMS."}


@router.get("/sites/{site_id}/content/drafts")
def list_drafts(site_id: uuid.UUID, ctx: Ctx = Depends(get_ctx)) -> list[dict[str, Any]]:
    site = ctx.site(site_id)
    return [_draft_out(d) for d in ctx.db.execute(select(ContentDraft).where(ContentDraft.site_id == site.id)
                                                  .order_by(ContentDraft.created_at.desc())).scalars()]


def _draft(ctx: Ctx, draft_id: uuid.UUID, perm: str) -> ContentDraft:
    d = ctx.db.get(ContentDraft, draft_id)
    if d is None:
        raise NotFound("Draft not found")
    ctx.site(d.site_id, perm)
    return d


@router.post("/content/drafts/{draft_id}/{action}")
def review_draft(draft_id: uuid.UUID, action: str, body: ContentReviewIn | None = None, ctx: Ctx = Depends(get_ctx)) -> dict[str, Any]:
    transitions = {"save": ("content:write", {"draft", "rejected"}, None), "submit": ("content:write", {"draft", "rejected"}, "in_review"),
                   "approve": ("content:approve", {"in_review"}, "approved"), "reject": ("content:approve", {"in_review"}, "rejected")}
    if action not in transitions:
        raise NotFound("Unknown action")
    perm, allowed, target = transitions[action]
    d = _draft(ctx, draft_id, perm)
    if d.status not in allowed:
        raise Conflict(f"Cannot {action} a draft in status '{d.status}'.")
    if body and body.body is not None and action in ("save", "submit"):
        d.body = body.body
    if body and body.notes:
        d.review_notes = body.notes
    if target:
        d.status = target
    if action == "approve":
        d.editorial_approved_by, d.editorial_approved_at = ctx.user.id, utcnow()
    audit.record(ctx.db, tenant_id=ctx.tenant.id, action=f"content.{action}", actor_id=ctx.user.id, actor_label=ctx.user.email,
                 target_type="content_draft", target_id=d.id, site_id=d.site_id)
    return _draft_out(d)
