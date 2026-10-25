from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Header, Query
from fastapi.responses import JSONResponse, Response
from sqlalchemy import case, func, or_, select

from aseo.api.deps import Ctx, get_ctx, idempotent, paginate, require
from aseo.api.schemas import (
    CapabilityOut,
    ConnectorIn,
    ConnectorOut,
    CrawlIn,
    CrawlOut,
    FindingOut,
    OccurrenceOut,
    Page_,
    PageOut,
    SiteIn,
    SiteOut,
    SiteUpdateIn,
    VerificationOut,
    VerificationStartIn,
)
from aseo.core.errors import NotFound
from aseo.models import (
    ChangeSet,
    Connector,
    ConnectorCapability,
    CrawlJob,
    FindingOccurrence,
    Page,
    PageSnapshot,
    SeoFinding,
    Site,
    SiteVerification,
)
from aseo.services import audit, crawls
from aseo.services import connectors as connector_svc
from aseo.services import sites as site_svc

router = APIRouter(tags=["sites"])
SEV_RANK = case({"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}, value=SeoFinding.severity, else_=5)


@router.post("/sites", response_model=SiteOut, status_code=201, summary="Register a website")
def create_site(body: SiteIn, ctx: Ctx = Depends(require("site:create"))) -> SiteOut:
    site = site_svc.create_site(ctx.db, tenant_id=ctx.tenant.id, actor_id=ctx.user.id, actor_label=ctx.user.email, name=body.name,
                                url=body.url, platform=body.platform, workspace_id=body.workspace_id, crawl_settings=body.crawl_settings,
                                business_goals=body.business_goals)
    if body.workspace_id:
        ctx.site(site.id, "site:create")  # enforce workspace boundary for scoped users
    return SiteOut.model_validate(site)


@router.get("/sites", response_model=list[SiteOut])
def list_sites(workspace_id: uuid.UUID | None = None, ctx: Ctx = Depends(require("site:read"))) -> list[SiteOut]:
    q = select(Site).where(ctx.site_filter())
    if workspace_id:
        q = q.where(Site.workspace_id == workspace_id)
    return [SiteOut.model_validate(s) for s in ctx.db.execute(q.order_by(Site.created_at)).scalars()]


@router.get("/sites/{site_id}", response_model=SiteOut)
def get_site(site_id: uuid.UUID, ctx: Ctx = Depends(get_ctx)) -> SiteOut:
    return SiteOut.model_validate(ctx.site(site_id))


@router.patch("/sites/{site_id}", response_model=SiteOut)
def update_site(site_id: uuid.UUID, body: SiteUpdateIn, ctx: Ctx = Depends(get_ctx)) -> SiteOut:
    site = ctx.site(site_id, "site:manage")
    data = body.model_dump(exclude_none=True)
    if "crawl_settings" in data:
        allowed = {"max_pages", "max_depth", "include_paths", "exclude_paths", "respect_robots"}
        cs = {k: v for k, v in data.pop("crawl_settings").items() if k in allowed}
        site.crawl_settings = {**site.crawl_settings, **cs}
    for k, v in data.items():
        setattr(site, k, v)
    audit.record(ctx.db, tenant_id=ctx.tenant.id, action="site.updated", actor_id=ctx.user.id, actor_label=ctx.user.email,
                 target_type="site", target_id=site.id, site_id=site.id, data={"fields": sorted(body.model_dump(exclude_none=True))})
    return SiteOut.model_validate(site)


@router.get("/sites/{site_id}/overview", summary="Dashboard aggregate for a site")
def overview(site_id: uuid.UUID, ctx: Ctx = Depends(get_ctx)) -> dict[str, Any]:
    site = ctx.site(site_id)
    db = ctx.db
    sev = dict(db.execute(select(SeoFinding.severity, func.count()).where(SeoFinding.site_id == site.id, SeoFinding.status == "open")
                          .group_by(SeoFinding.severity)).all())
    kinds = dict(db.execute(select(SeoFinding.kind, func.count()).where(SeoFinding.site_id == site.id, SeoFinding.status == "open")
                            .group_by(SeoFinding.kind)).all())
    top = db.execute(select(SeoFinding).where(SeoFinding.site_id == site.id, SeoFinding.status == "open")
                     .order_by(SEV_RANK, SeoFinding.affected_count.desc()).limit(6)).scalars()
    changes = dict(db.execute(select(ChangeSet.status, func.count()).where(ChangeSet.site_id == site.id).group_by(ChangeSet.status)).all())
    crawl_hist = db.execute(select(CrawlJob).where(CrawlJob.site_id == site.id, CrawlJob.status == "completed")
                            .order_by(CrawlJob.finished_at.desc()).limit(12)).scalars().all()
    pages = db.execute(select(func.count()).select_from(Page).where(Page.site_id == site.id)).scalar_one()
    return {
        "site": SiteOut.model_validate(site).model_dump(mode="json"),
        "pages": pages,
        "findings_by_severity": sev,
        "findings_by_kind": kinds,
        "top_findings": [FindingOut.model_validate(f).model_dump(mode="json") for f in top],
        "changes_by_status": changes,
        "health_history": [{"crawl_id": str(c.id), "at": c.finished_at.isoformat() if c.finished_at else None,
                            "score": (c.stats or {}).get("health"), "pages": c.pages_crawled} for c in reversed(crawl_hist)],
        "health_label": "Internal diagnostic score — not a Google score",
    }


# ------------------------------------------------------------------ verification


@router.post("/sites/{site_id}/verification/start", summary="Start domain-ownership verification")
def start_verification(site_id: uuid.UUID, body: VerificationStartIn, ctx: Ctx = Depends(get_ctx)) -> dict[str, Any]:
    site = ctx.site(site_id, "site:manage")
    v, instr = site_svc.start_verification(ctx.db, site, body.method)
    return {"verification": VerificationOut.model_validate(v).model_dump(mode="json"), "instructions": instr, "token": v.token}


@router.post("/sites/{site_id}/verification/check", response_model=VerificationOut, summary="Check domain-ownership verification")
def check_verification(site_id: uuid.UUID, ctx: Ctx = Depends(get_ctx)) -> VerificationOut:
    site = ctx.site(site_id, "site:manage")
    v = site_svc.latest_verification(ctx.db, site)
    if v is None:
        raise NotFound("Start verification first.")
    return VerificationOut.model_validate(site_svc.check_verification(ctx.db, site, v))


@router.get("/sites/{site_id}/verification", response_model=VerificationOut | None)
def get_verification(site_id: uuid.UUID, ctx: Ctx = Depends(get_ctx)) -> VerificationOut | None:
    v = site_svc.latest_verification(ctx.db, ctx.site(site_id))
    return VerificationOut.model_validate(v) if v else None


# ------------------------------------------------------------------ connectors


def _connector_out(ctx: Ctx, c: Connector) -> ConnectorOut:
    caps = ctx.db.execute(select(ConnectorCapability).where(ConnectorCapability.connector_id == c.id)
                          .order_by(ConnectorCapability.supported.desc(), ConnectorCapability.action_type)).scalars()
    return ConnectorOut(id=c.id, provider=c.provider, status=c.status, mode=c.mode, config=c.config, scopes=c.scopes,
                        last_checked_at=c.last_checked_at, last_error=c.last_error,
                        capabilities=[CapabilityOut.model_validate(x) for x in caps], secrets=connector_svc.secret_status(ctx.db, c.id))


@router.get("/sites/{site_id}/connectors", response_model=list[ConnectorOut])
def list_connectors(site_id: uuid.UUID, ctx: Ctx = Depends(get_ctx)) -> list[ConnectorOut]:
    site = ctx.site(site_id)
    return [_connector_out(ctx, c) for c in site_svc.connectors_for(ctx.db, site)]


@router.post("/sites/{site_id}/connectors", response_model=ConnectorOut, status_code=201,
             summary="Connect a platform with credentials (WordPress application password, Shopify token, GitHub installation)")
def connect(site_id: uuid.UUID, body: ConnectorIn, ctx: Ctx = Depends(get_ctx)) -> ConnectorOut:
    site = ctx.site(site_id, "connector:manage")
    if body.mode == "fixture":
        site_svc.push_fixture_token(ctx.db, site)
    c = connector_svc.connect(ctx.db, site=site, provider=body.provider, config=body.config, secrets=body.secrets, mode=body.mode)
    audit.record(ctx.db, tenant_id=ctx.tenant.id, action="connector.connected", actor_id=ctx.user.id, actor_label=ctx.user.email,
                 target_type="connector", target_id=c.id, site_id=site.id,
                 data={"provider": c.provider, "mode": c.mode, "status": c.status, "secret_names": sorted(body.secrets)})
    return _connector_out(ctx, c)


@router.post("/sites/{site_id}/connectors/{connector_id}/check", response_model=ConnectorOut)
def check_connector(site_id: uuid.UUID, connector_id: uuid.UUID, ctx: Ctx = Depends(get_ctx)) -> ConnectorOut:
    site = ctx.site(site_id, "connector:manage")
    c = connector_svc.get_site_connector(ctx.db, connector_id)
    if c.site_id != site.id:
        raise NotFound("Connector not found")
    return _connector_out(ctx, connector_svc.check(ctx.db, site, c))


@router.delete("/sites/{site_id}/connectors/{connector_id}", status_code=204, response_class=Response)
def disconnect(site_id: uuid.UUID, connector_id: uuid.UUID, ctx: Ctx = Depends(get_ctx)) -> Response:
    site = ctx.site(site_id, "connector:manage")
    c = connector_svc.get_site_connector(ctx.db, connector_id)
    if c.site_id != site.id:
        raise NotFound("Connector not found")
    connector_svc.disconnect(ctx.db, c)
    audit.record(ctx.db, tenant_id=ctx.tenant.id, action="connector.disconnected", actor_id=ctx.user.id, actor_label=ctx.user.email,
                 target_type="connector", target_id=c.id, site_id=site.id, data={"provider": c.provider, "secrets_revoked": True})
    return Response(status_code=204)


# ------------------------------------------------------------------ crawls


@router.post("/sites/{site_id}/crawls", status_code=202, response_model=CrawlOut, summary="Queue a crawl (deduplicated, budget-checked)")
def start_crawl(site_id: uuid.UUID, body: CrawlIn | None = None, ctx: Ctx = Depends(get_ctx),
                idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")) -> JSONResponse:
    site = ctx.site(site_id, "crawl:run")
    overrides = (body or CrawlIn()).model_dump(exclude_none=True)

    def go() -> tuple[int, Any]:
        job, created = crawls.schedule_crawl(ctx.db, site, trigger="manual", requested_by=ctx.user.id, overrides=overrides)
        return 202, {**CrawlOut.model_validate(job).model_dump(mode="json"), "deduplicated": not created}

    status, payload = idempotent(ctx, idempotency_key, {"site": str(site_id), **overrides}, go)
    return JSONResponse(payload, status_code=status, headers={"location": f"/api/v1/crawls/{payload['id']}"})


@router.get("/crawls/{crawl_id}", response_model=CrawlOut)
def get_crawl(crawl_id: uuid.UUID, ctx: Ctx = Depends(get_ctx)) -> CrawlOut:
    job = ctx.db.get(CrawlJob, crawl_id)
    if job is None:
        raise NotFound("Crawl not found")
    ctx.site(job.site_id)
    return CrawlOut.model_validate(job)


@router.get("/sites/{site_id}/crawls", response_model=list[CrawlOut])
def list_crawls(site_id: uuid.UUID, ctx: Ctx = Depends(get_ctx)) -> list[CrawlOut]:
    site = ctx.site(site_id)
    rows = ctx.db.execute(select(CrawlJob).where(CrawlJob.site_id == site.id).order_by(CrawlJob.created_at.desc()).limit(30)).scalars()
    return [CrawlOut.model_validate(j) for j in rows]


# ------------------------------------------------------------------ pages


@router.get("/sites/{site_id}/pages", response_model=Page_[PageOut], summary="Crawled URLs (cursor-paginated)")
def list_pages(site_id: uuid.UUID, q: str | None = None, status: int | None = None, indexable: bool | None = None,
               issue: str | None = Query(default=None, description="Only pages affected by this rule key"),
               cursor: str | None = None, limit: int = 50, ctx: Ctx = Depends(get_ctx)) -> Page_[PageOut]:
    site = ctx.site(site_id)
    query = select(Page).where(Page.site_id == site.id)
    if q:
        like = f"%{q.lower()}%"
        query = query.where(or_(func.lower(Page.url).like(like), func.lower(Page.title).like(like)))
    if status is not None:
        query = query.where(Page.status_code == status)
    if indexable is not None:
        query = query.where(Page.indexable.is_(indexable))
    if issue:
        sub = select(FindingOccurrence.page_id).join(SeoFinding, SeoFinding.id == FindingOccurrence.finding_id).where(
            SeoFinding.site_id == site.id, SeoFinding.rule_key == issue)
        query = query.where(Page.id.in_(sub))
    rows, nxt = paginate(ctx.db, query, Page, cursor, limit)
    return Page_[PageOut](items=[PageOut.model_validate(p) for p in rows], next_cursor=nxt)


@router.get("/pages/{page_id}", summary="Page detail with latest snapshot and findings")
def get_page(page_id: uuid.UUID, ctx: Ctx = Depends(get_ctx)) -> dict[str, Any]:
    page = ctx.db.get(Page, page_id)
    if page is None:
        raise NotFound("Page not found")
    ctx.site(page.site_id)
    snaps = ctx.db.execute(select(PageSnapshot).where(PageSnapshot.page_id == page.id).order_by(PageSnapshot.created_at.desc()).limit(10)).scalars().all()
    occ = ctx.db.execute(select(FindingOccurrence, SeoFinding).join(SeoFinding, SeoFinding.id == FindingOccurrence.finding_id)
                         .where(FindingOccurrence.page_id == page.id)).all()
    return {
        "page": PageOut.model_validate(page).model_dump(mode="json"),
        "snapshot": snaps[0].extracted if snaps else None,
        "snapshot_id": str(snaps[0].id) if snaps else None,
        "snapshots": [{"id": str(s.id), "crawl_job_id": str(s.crawl_job_id), "status_code": s.status_code, "content_hash": s.content_hash,
                       "changed": s.changed, "fetched_at": s.fetched_at.isoformat() if s.fetched_at else None,
                       "redirect_chain": s.redirect_chain, "response_ms": s.response_ms} for s in snaps],
        "findings": [{"finding_id": str(f.id), "rule_key": f.rule_key, "title": f.title, "severity": f.severity, "kind": f.kind,
                      "fix_action": f.fix_action, "status": o.status, "evidence": o.evidence} for o, f in occ],
    }


# ------------------------------------------------------------------ findings


@router.get("/sites/{site_id}/findings", response_model=list[FindingOut])
def list_findings(site_id: uuid.UUID, status: str = "open", severity: str | None = None, category: str | None = None,
                  kind: str | None = None, ctx: Ctx = Depends(get_ctx)) -> list[FindingOut]:
    site = ctx.site(site_id, "finding:read")
    q = select(SeoFinding).where(SeoFinding.site_id == site.id)
    if status != "all":
        q = q.where(SeoFinding.status == status)
    if severity:
        q = q.where(SeoFinding.severity == severity)
    if category:
        q = q.where(SeoFinding.category == category)
    if kind:
        q = q.where(SeoFinding.kind == kind)
    return [FindingOut.model_validate(f) for f in ctx.db.execute(q.order_by(SEV_RANK, SeoFinding.affected_count.desc())).scalars()]


@router.get("/findings/{finding_id}")
def get_finding(finding_id: uuid.UUID, ctx: Ctx = Depends(get_ctx)) -> dict[str, Any]:
    f = ctx.db.get(SeoFinding, finding_id)
    if f is None:
        raise NotFound("Finding not found")
    ctx.site(f.site_id, "finding:read")
    occ = ctx.db.execute(select(FindingOccurrence).where(FindingOccurrence.finding_id == f.id).limit(500)).scalars()
    changes = ctx.db.execute(select(ChangeSet).where(ChangeSet.finding_id == f.id).order_by(ChangeSet.created_at.desc())).scalars()
    return {"finding": FindingOut.model_validate(f).model_dump(mode="json"),
            "occurrences": [OccurrenceOut.model_validate(o).model_dump(mode="json") for o in occ],
            "change_sets": [{"id": str(c.id), "status": c.status, "title": c.title, "page_id": str(c.page_id) if c.page_id else None} for c in changes]}


@router.post("/findings/{finding_id}/status", response_model=FindingOut)
def set_finding_status(finding_id: uuid.UUID, status: str, ctx: Ctx = Depends(get_ctx)) -> FindingOut:
    f = ctx.db.get(SeoFinding, finding_id)
    if f is None:
        raise NotFound("Finding not found")
    ctx.site(f.site_id, "finding:manage")
    if status not in ("open", "ignored"):
        raise NotFound("Unsupported status")
    f.status = status
    audit.record(ctx.db, tenant_id=ctx.tenant.id, action=f"finding.{status}", actor_id=ctx.user.id, actor_label=ctx.user.email,
                 target_type="finding", target_id=f.id, site_id=f.site_id)
    return FindingOut.model_validate(f)


_ = SiteVerification
