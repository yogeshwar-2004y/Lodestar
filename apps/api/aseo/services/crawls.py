"""Crawl jobs: scheduling (budget-checked, deduplicated), execution, persistence of pages,
snapshots, link edges, findings and the internal health score."""

from __future__ import annotations

import logging
import uuid
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from aseo.core.config import get_settings
from aseo.core.db import tenant_session
from aseo.core.errors import Conflict
from aseo.core.security import sha256_hex
from aseo.crawler.engine import CrawlConfig, crawl
from aseo.crawler.urls import url_hash
from aseo.models import CrawlEdge, CrawlJob, FindingOccurrence, Page, PageSnapshot, SeoFinding, SeoRule, Site
from aseo.models.base import utcnow
from aseo.rules.engine import RULES, Dataset, PageData, evaluate, health_score
from aseo.services import audit, billing, notifications, outbox
from aseo.services import connectors as connector_svc
from aseo.services.storage import get_storage

log = logging.getLogger("aseo.crawls")
ACTIVE = ("queued", "running")


def schedule_crawl(db: Session, site: Site, *, trigger: str, requested_by: uuid.UUID | None = None,
                   overrides: dict[str, Any] | None = None) -> tuple[CrawlJob, bool]:
    """Returns (job, created). An active crawl for the site is reused (deduplication)."""
    active = db.execute(select(CrawlJob).where(CrawlJob.site_id == site.id, CrawlJob.status.in_(ACTIVE))).scalars().first()
    if active is not None:
        return active, False
    settings = {**site.crawl_settings, **(overrides or {})}
    plan_cap = billing.max_pages_allowed(db, site.tenant_id)
    settings["max_pages"] = max(1, min(int(settings.get("max_pages", 100)), plan_cap, get_settings().crawler_max_pages * 50))
    cost = billing.crawl_credit_cost(settings["max_pages"])
    billing.check_budget(db, site.tenant_id, cost)  # before scheduling
    job = CrawlJob(tenant_id=site.tenant_id, site_id=site.id, status="queued", trigger=trigger, settings=settings,
                   requested_by=requested_by, dedupe_key=f"crawl:{site.id}:{utcnow():%Y%m%d%H%M%S}")
    db.add(job)
    db.flush()
    billing.post(db, site.tenant_id, -cost, reason="crawl", idempotency_key=f"crawl:{job.id}", ref_type="crawl_job", ref_id=str(job.id),
                 meta={"reserved_pages": settings["max_pages"]})
    outbox.enqueue(db, "crawl.run", {"crawl_id": str(job.id)}, tenant_id=site.tenant_id, dedupe_key=f"crawl:{job.id}")
    audit.record(db, tenant_id=site.tenant_id, action="crawl.scheduled", actor_type="user" if requested_by else "system",
                 actor_id=requested_by, target_type="crawl_job", target_id=job.id, site_id=site.id,
                 data={"trigger": trigger, "max_pages": settings["max_pages"], "credits_reserved": cost})
    return job, True


def cancel_crawl(db: Session, job: CrawlJob) -> None:
    if job.status != "queued":
        raise Conflict("Only queued crawls can be cancelled.")
    job.status = "cancelled"
    job.finished_at = utcnow()


def _persist(db: Session, site: Site, job: CrawlJob, out: Any) -> dict[str, Any]:
    storage = get_storage()
    now = utcnow()
    existing = {p.url_hash: p for p in db.execute(select(Page).where(Page.site_id == site.id)).scalars()}
    pages_by_url: dict[str, Page] = {}
    snapshots: dict[str, PageSnapshot] = {}
    changed = 0
    for pr in out.pages:
        h = url_hash(pr.url)
        page = existing.get(h)
        if page is None:
            page = Page(tenant_id=site.tenant_id, site_id=site.id, url=pr.url, url_hash=h, path=urlsplit(pr.url).path or "/",
                        first_seen_at=now)
            db.add(page)
            existing[h] = page
        ex = pr.extracted
        content_changed = pr.content_hash is not None and pr.content_hash != page.content_hash
        changed += int(content_changed)
        page.status_code = pr.status_code or None
        page.content_type = pr.headers.get("content-type")
        page.title = ex.get("title")
        page.meta_description = ex.get("meta_description")
        page.h1 = (ex.get("h1") or [None])[0]
        page.canonical = ex.get("canonical")
        page.robots_meta = ex.get("robots_meta")
        page.word_count = ex.get("word_count")
        page.in_sitemap = pr.in_sitemap
        page.depth = pr.depth
        page.response_ms = pr.elapsed_ms
        page.redirect_target = pr.final_url if pr.redirect_chain else None
        page.content_hash = pr.content_hash or page.content_hash
        page.last_crawl_id = job.id
        page.last_seen_at = now
        page.outlinks = len(ex.get("links", []))
        db.flush()
        storage_key = None
        if pr.html is not None and pr.content_hash:
            storage_key = storage.put(f"{site.tenant_id}/{site.id}/{pr.content_hash}.html", pr.html.encode())
        extracted = {k: v for k, v in ex.items() if k not in ("links",)}
        extracted["link_count"] = len(ex.get("links", []))
        snap = PageSnapshot(tenant_id=site.tenant_id, page_id=page.id, crawl_job_id=job.id, status_code=pr.status_code,
                            final_url=pr.final_url, redirect_chain=pr.redirect_chain, headers=pr.headers, content_hash=pr.content_hash,
                            changed=content_changed, storage_key=storage_key, extracted=extracted, byte_size=len(pr.html or ""),
                            response_ms=pr.elapsed_ms, fetched_at=now)
        if pr.blocked_by_robots:
            snap.extracted = {"blocked_by_robots": True}
        db.add(snap)
        db.flush()
        page.last_snapshot_id = snap.id
        pages_by_url[pr.url] = page
        snapshots[pr.url] = snap

    inlinks: dict[str, int] = {}
    edges = []
    for pr in out.pages:
        src = pages_by_url.get(pr.url)
        for link in pr.extracted.get("links", [])[:500]:
            target = pages_by_url.get(link["href"])
            internal = target is not None or urlsplit(link["href"]).netloc == site.domain
            if internal:
                inlinks[link["href"]] = inlinks.get(link["href"], 0) + 1
            edges.append(CrawlEdge(tenant_id=site.tenant_id, crawl_job_id=job.id, source_page_id=src.id, target_url=link["href"],
                                   target_page_id=target.id if target else None, anchor_text=(link.get("text") or "")[:300],
                                   nofollow=link.get("nofollow", False), is_internal=internal))
    db.add_all(edges)
    for url, page in pages_by_url.items():
        page.inlinks = inlinks.get(url, 0)
        page.indexable = None
    db.flush()

    dataset = Dataset(
        site_host=site.domain,
        pages=[PageData(pr.url, pr.status_code, pr.final_url, pr.depth, pr.in_sitemap, pr.redirect_chain, pr.extracted, pr.headers,
                        pr.elapsed_ms, str(pages_by_url[pr.url].id), str(snapshots[pr.url].id), pr.blocked_by_robots) for pr in out.pages],
        sitemap_urls=out.sitemap_page_urls, sitemap_files=out.sitemap_urls, robots_found=out.robots_txt is not None,
    )
    for pd in dataset.pages:
        pages_by_url[pd.url].indexable = pd.indexable
    results = evaluate(dataset)
    _sync_findings(db, site, job, results)
    hs = health_score(dataset, results)
    site.health_score = hs["score"]
    site.health_breakdown = hs
    return {"changed_pages": changed, "findings": len(results), "health": hs["score"]}


def _sync_findings(db: Session, site: Site, job: CrawlJob, results: list[Any]) -> None:
    existing = {f.fingerprint: f for f in db.execute(select(SeoFinding).where(SeoFinding.site_id == site.id)).scalars()}
    seen: set[str] = set()
    for r in results:
        rule = RULES[r.rule_key]
        fp = r.fingerprint()
        seen.add(fp)
        f = existing.get(fp)
        if f is None:
            f = SeoFinding(tenant_id=site.tenant_id, site_id=site.id, rule_key=r.rule_key, fingerprint=fp, first_seen_crawl_id=job.id,
                           severity=rule.severity, kind=rule.kind, category=rule.category, title=r.title, summary=r.summary,
                           remediation=rule.remediation, fix_action=rule.fix_action)
            db.add(f)
        if f.status in ("resolved",):
            f.status = "open"
        f.title, f.summary, f.severity = r.title, r.summary, rule.severity
        f.last_seen_crawl_id = job.id
        f.affected_count = len(r.occurrences)
        f.evidence = {**r.evidence, "rule_version": 1, "kind": rule.kind, "sample": [o.evidence for o in r.occurrences[:3]]}
        db.flush()
        db.execute(delete(FindingOccurrence).where(FindingOccurrence.finding_id == f.id))
        for o in r.occurrences:
            db.add(FindingOccurrence(tenant_id=site.tenant_id, finding_id=f.id, page_id=uuid.UUID(o.page_id) if o.page_id else None,
                                     snapshot_id=uuid.UUID(o.snapshot_id) if o.snapshot_id else None, crawl_job_id=job.id, url=o.url,
                                     evidence=o.evidence))
    for fp, f in existing.items():
        if fp not in seen and f.status in ("open", "fix_pending"):
            f.status = "resolved"
            f.affected_count = 0
            f.last_seen_crawl_id = job.id
            db.execute(delete(FindingOccurrence).where(FindingOccurrence.finding_id == f.id))
    db.flush()


def run_crawl(crawl_id: uuid.UUID, tenant_id: uuid.UUID) -> None:
    with tenant_session(tenant_id) as db:
        job = db.get(CrawlJob, crawl_id)
        if job is None or job.status != "queued":
            return
        site = db.get(Site, job.site_id)
        assert site is not None
        job.status = "running"
        job.started_at = utcnow()
        cfg = CrawlConfig(
            base_url=site.base_url, site_host=site.domain, max_pages=int(job.settings.get("max_pages", 100)),
            max_depth=int(job.settings.get("max_depth", 6)), include_paths=job.settings.get("include_paths") or [],
            exclude_paths=job.settings.get("exclude_paths") or [], respect_robots=bool(job.settings.get("respect_robots", True)),
            user_agent=get_settings().crawler_user_agent, concurrency=get_settings().crawler_concurrency_per_host,
            delay_seconds=get_settings().crawler_default_delay_seconds,
        )
        db.commit()
    try:
        out = connector_svc.run(crawl(cfg))
    except Exception as exc:  # noqa: BLE001
        with tenant_session(tenant_id) as db:
            job = db.get(CrawlJob, crawl_id)
            job.status = "failed"
            job.error = f"{type(exc).__name__}: {exc}"[:500]
            job.finished_at = utcnow()
            reserved = _reserved(db, job)
            if reserved:
                billing.post(db, tenant_id, reserved, reason="refund", idempotency_key=f"crawl-refund:{job.id}",
                             ref_type="crawl_job", ref_id=str(job.id))
        raise outbox.PermanentJobError(str(exc)) from exc
    with tenant_session(tenant_id) as db:
        job = db.get(CrawlJob, crawl_id)
        site = db.get(Site, job.site_id)
        summary = _persist(db, site, job, out)
        job.status = "completed"
        job.finished_at = utcnow()
        job.pages_crawled = len(out.pages)
        job.robots_txt = (out.robots_txt or "")[:20000] or None
        job.sitemaps = out.sitemap_urls
        job.stats = {**out.stats, **summary}
        site.last_crawl_at = utcnow()
        reserved = _reserved(db, job)
        actual = billing.crawl_credit_cost(len(out.pages))
        if reserved > actual:
            billing.post(db, tenant_id, reserved - actual, reason="refund", idempotency_key=f"crawl-refund:{job.id}",
                         ref_type="crawl_job", ref_id=str(job.id), meta={"pages": len(out.pages)})
        billing.record_usage(db, tenant_id, "pages_crawled", len(out.pages), "crawl_job", str(job.id))
        audit.record(db, tenant_id=tenant_id, action="crawl.completed", actor_type="system", target_type="crawl_job", target_id=job.id,
                     site_id=site.id, data={"pages": len(out.pages), **summary})
        notifications.notify(db, tenant_id, kind="crawl_completed", severity="success", title=f"Audit finished for {site.name}",
                             body=f"{len(out.pages)} pages · health {summary['health']}", link=f"/app/sites/{site.id}/audit")
        outbox.enqueue(db, "agents.post_crawl", {"crawl_id": str(job.id)}, tenant_id=tenant_id, dedupe_key=f"postcrawl:{job.id}")


def _reserved(db: Session, job: CrawlJob) -> int:
    from aseo.models import CreditLedger

    entry = db.execute(select(CreditLedger).where(CreditLedger.idempotency_key == f"crawl:{job.id}")).scalar_one_or_none()
    return -entry.delta if entry else 0


@outbox.handler("crawl.run")
def _h_crawl(payload: dict[str, Any], tenant_id: uuid.UUID | None) -> None:
    assert tenant_id
    run_crawl(uuid.UUID(payload["crawl_id"]), tenant_id)


def sync_rule_catalogue(db: Session) -> None:
    existing = {r.key: r for r in db.execute(select(SeoRule)).scalars()}
    for key, r in RULES.items():
        row = existing.get(key) or SeoRule(key=key)
        row.category, row.title, row.description, row.severity = r.category, r.title, r.description, r.severity
        row.kind, row.weight, row.remediation, row.fix_action = r.kind, r.weight, r.remediation, r.fix_action
        if key not in existing:
            db.add(row)
    db.flush()


_ = sha256_hex
