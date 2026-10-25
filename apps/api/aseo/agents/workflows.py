"""Persisted workflow orchestration (typed state machine; each step is recorded in
``workflow_runs.steps`` so runs are inspectable and resumable)."""

from __future__ import annotations

import logging
import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from aseo.agents import agents
from aseo.core.db import system_session, tenant_session
from aseo.core.errors import AppError
from aseo.models import (
    AutomationPolicy,
    AutomationSchedule,
    ChangeSet,
    CrawlJob,
    FindingOccurrence,
    SeoFinding,
    Site,
    Tenant,
    WorkflowRun,
)
from aseo.models.base import utcnow
from aseo.services import changes, crawls, outbox
from aseo.services import connectors as connector_svc

log = logging.getLogger("aseo.workflows")
MAX_AUTO_PROPOSALS = 3


def _step(wf: WorkflowRun, name: str, status: str, **data: Any) -> None:
    steps = list(wf.steps or [])
    steps = [s for s in steps if s["name"] != name] + [{"name": name, "status": status, "at": utcnow().isoformat(), **data}]
    wf.steps = steps
    wf.current_step = name


def post_crawl(crawl_id: uuid.UUID, tenant_id: uuid.UUID) -> None:
    with tenant_session(tenant_id) as db:
        job = db.get(CrawlJob, crawl_id)
        site = db.get(Site, job.site_id) if job else None
        if not job or not site:
            return
        wf = WorkflowRun(tenant_id=tenant_id, site_id=site.id, kind="post_crawl", status="running", trigger=job.trigger,
                         started_at=utcnow(), state={"crawl_id": str(crawl_id)})
        db.add(wf)
        db.flush()
        wf_id = wf.id
    for step in ("audit", "strategy", "proposals"):
        with tenant_session(tenant_id) as db:
            wf = db.get(WorkflowRun, wf_id)
            site = db.get(Site, wf.site_id)
            try:
                with db.begin_nested():
                    _run_step(db, wf, site, step)
            except Exception as exc:  # noqa: BLE001 — record and stop; never re-run a partial workflow
                message = exc.message if isinstance(exc, AppError) else f"{type(exc).__name__}: {exc}"
                log.exception("workflow step failed")
                _step(wf, step, "failed", error=message[:500])
                wf.status = "failed" if step != "proposals" else "completed_with_errors"
                wf.error = message[:500]
                wf.finished_at = utcnow()
                return
    with tenant_session(tenant_id) as db:
        wf = db.get(WorkflowRun, wf_id)
        wf.status = "completed"
        wf.finished_at = utcnow()


def _run_step(db: Session, wf: WorkflowRun, site: Site, step: str) -> None:
    if step == "audit":
        run = agents.audit_agent(db, site, workflow_run_id=wf.id)
        _step(wf, "audit", "succeeded", agent_run_id=str(run.id), provider=run.provider)
    elif step == "strategy":
        run, plan = agents.strategy_agent(db, site, workflow_run_id=wf.id)
        _step(wf, "strategy", "succeeded", agent_run_id=str(run.id), plan_id=str(plan.id), provider=run.provider)
    elif step == "proposals":
        created = _auto_propose(db, site)
        _step(wf, "proposals", "succeeded", change_sets=[str(c) for c in created])


def _auto_propose(db: Session, site: Site) -> list[uuid.UUID]:
    """Ask the Execution Agent to prepare patches for the highest-value metadata fixes.
    In Assist mode these land in the approval inbox; in Autopilot they may auto-execute if
    every policy check passes. Observe mode creates nothing."""
    pol = db.execute(select(AutomationPolicy).where(AutomationPolicy.site_id == site.id)).scalar_one_or_none()
    tenant = db.get(Tenant, site.tenant_id)
    connector = connector_svc.write_connector_for(db, site)
    if not pol or pol.mode == "observe" or pol.paused or tenant.kill_switch or not site.verified_at or not connector or connector.status != "connected":
        return []
    rows = db.execute(
        select(FindingOccurrence, SeoFinding).join(SeoFinding, SeoFinding.id == FindingOccurrence.finding_id)
        .where(SeoFinding.site_id == site.id, SeoFinding.rule_key == "missing_meta_description", FindingOccurrence.status == "open")
        .limit(10)
    ).all()
    created: list[uuid.UUID] = []
    for occ, finding in rows:
        if len(created) >= MAX_AUTO_PROPOSALS:
            break
        exists = db.execute(select(ChangeSet.id).where(ChangeSet.site_id == site.id, ChangeSet.page_id == occ.page_id,
                                                       ChangeSet.action_type == "meta_description",
                                                       ChangeSet.status.notin_(["rejected", "rolled_back", "cancelled", "failed"]))).first()
        if exists:
            continue
        try:
            cs = agents.execution_agent_propose(db, site, url=occ.url, action_type="meta_description", finding_id=finding.id,
                                                actor=changes.Actor("agent", None, "Execution Agent"))
            created.append(cs.id)
        except AppError as exc:
            log.warning("auto proposal skipped: %s", exc.message)
    return created


def after_change(change_set_id: uuid.UUID, tenant_id: uuid.UUID) -> None:
    with tenant_session(tenant_id) as db:
        cs = db.get(ChangeSet, change_set_id)
        site = db.get(Site, cs.site_id) if cs else None
        if cs and site:
            agents.measurement_agent(db, site, cs)


def scheduler_tick() -> int:
    """Start due scheduled crawls. Safe to run concurrently (row locks + crawl dedupe)."""
    started = 0
    with system_session() as db:
        due = db.execute(select(AutomationSchedule).where(AutomationSchedule.enabled.is_(True), AutomationSchedule.kind == "crawl",
                                                          AutomationSchedule.next_run_at.isnot(None),
                                                          AutomationSchedule.next_run_at <= utcnow())
                         .with_for_update(skip_locked=True).limit(20)).scalars().all()
        jobs = [(s.id, s.site_id, s.tenant_id) for s in due]
        for s in due:
            s.next_run_at = utcnow() + timedelta(minutes=s.interval_minutes)
            s.last_run_at = utcnow()
    for _sid, site_id, tenant_id in jobs:
        try:
            with tenant_session(tenant_id) as db:
                site = db.get(Site, site_id)
                tenant = db.get(Tenant, tenant_id)
                pol = db.execute(select(AutomationPolicy).where(AutomationPolicy.site_id == site_id)).scalar_one_or_none()
                if site and site.verified_at and not tenant.kill_switch and not (pol and pol.paused):
                    crawls.schedule_crawl(db, site, trigger="schedule")
                    started += 1
        except AppError as exc:
            log.warning("scheduled crawl skipped: %s", exc.message)
    if started:
        outbox.kick()
    _maybe_run_retention()
    return started


_last_retention: dict[str, Any] = {"day": None}


def _maybe_run_retention() -> None:
    today = utcnow().date()
    if _last_retention["day"] == today:
        return
    from aseo.services import retention

    try:
        retention.run_daily()
        _last_retention["day"] = today
    except Exception:  # noqa: BLE001
        log.exception("retention job failed")


@outbox.handler("agents.post_crawl")
def _h_post_crawl(payload: dict[str, Any], tenant_id: uuid.UUID | None) -> None:
    assert tenant_id
    post_crawl(uuid.UUID(payload["crawl_id"]), tenant_id)


@outbox.handler("measurement.after_change")
def _h_measure(payload: dict[str, Any], tenant_id: uuid.UUID | None) -> None:
    assert tenant_id
    after_change(uuid.UUID(payload["change_set_id"]), tenant_id)
