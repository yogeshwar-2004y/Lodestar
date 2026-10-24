from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Header
from fastapi.responses import JSONResponse
from sqlalchemy import select

from aseo.agents import agents
from aseo.api.deps import Ctx, get_ctx, idempotent, paginate
from aseo.api.schemas import (
    ApprovalOut,
    ChangeSetDetail,
    ChangeSetIn,
    ChangeSetOut,
    CopilotIn,
    DecisionIn,
    ExecuteIn,
    ExecutionOut,
    Page_,
    PatchVersionOut,
    RejectIn,
    RollbackIn,
    ValidateIn,
)
from aseo.core.errors import NotFound, ValidationFailed
from aseo.models import (
    ActionPlan,
    AgentRun,
    Approval,
    ChangeSet,
    Connector,
    ExecutionRun,
    PatchVersion,
    PlanItem,
    RollbackSnapshot,
    Site,
    ToolInvocation,
    WorkflowRun,
)
from aseo.services import changes, outbox
from aseo.services import connectors as connector_svc

router = APIRouter(tags=["changes & agents"])


def _load(ctx: Ctx, change_id: uuid.UUID, permission: str = "site:read") -> ChangeSet:
    cs = ctx.db.get(ChangeSet, change_id)
    if cs is None:
        raise NotFound("Change set not found")
    ctx.site(cs.site_id, permission)
    return cs


def _detail(ctx: Ctx, cs: ChangeSet) -> ChangeSetDetail:
    db = ctx.db
    versions = db.execute(select(PatchVersion).where(PatchVersion.change_set_id == cs.id).order_by(PatchVersion.version.desc())).scalars().all()
    approvals = db.execute(select(Approval).where(Approval.change_set_id == cs.id).order_by(Approval.created_at.desc())).scalars().all()
    execs = db.execute(select(ExecutionRun).where(ExecutionRun.change_set_id == cs.id).order_by(ExecutionRun.created_at.desc())).scalars().all()
    connector = db.get(Connector, cs.connector_id) if cs.connector_id else None
    cap = connector_svc.capability_for(db, connector, cs.action_type)
    snap = db.execute(select(RollbackSnapshot).where(RollbackSnapshot.change_set_id == cs.id).limit(1)).scalar_one_or_none()
    rollback_available = bool(cs.status in changes.ROLLBACK_FROM and snap and snap.restorable and cap and cap.rollback_supported)
    note = None
    if cap and not cap.rollback_supported:
        note = "This connector cannot roll back automatically — restoring requires human action."
    elif cap and cap.write_mode == "pull_request":
        note = "Rollback opens a revert pull request; it is not live until merged and deployed."
    current = next((v for v in versions if v.id == cs.current_version_id), None)
    return ChangeSetDetail(
        **ChangeSetOut.model_validate(cs).model_dump(),
        current_version=PatchVersionOut.model_validate(current) if current else None,
        versions=[PatchVersionOut.model_validate(v) for v in versions],
        approvals=[ApprovalOut.model_validate(a) for a in approvals],
        executions=[ExecutionOut.model_validate(e) for e in execs],
        connector={"id": str(connector.id), "provider": connector.provider, "mode": connector.mode, "status": connector.status,
                   "write_mode": cap.write_mode if cap else "none", "rollback_supported": bool(cap and cap.rollback_supported)}
        if connector else None,
        rollback_available=rollback_available,
        rollback_note=note,
    )


@router.post("/change-sets", response_model=ChangeSetDetail, status_code=201,
             summary="Propose a change (empty value => Execution Agent drafts it)")
def create_change_set(body: ChangeSetIn, ctx: Ctx = Depends(get_ctx),
                      idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")) -> JSONResponse:
    site = ctx.site(body.site_id, "change:propose")

    def go() -> tuple[int, Any]:
        if body.value:
            cs = changes.propose(ctx.db, actor=ctx.actor, site=site, url=body.url, action_type=body.action_type, value=body.value,
                                 finding_id=body.finding_id, source="user", rationale=body.rationale)
        else:
            cs = agents.execution_agent_propose(ctx.db, site, url=body.url, action_type=body.action_type, finding_id=body.finding_id,
                                                actor=ctx.actor)
        ctx.db.flush()
        return 201, _detail(ctx, cs).model_dump(mode="json")

    status, payload = idempotent(ctx, idempotency_key, body.model_dump(mode="json"), go)
    return JSONResponse(payload, status_code=status)


@router.get("/change-sets", response_model=Page_[ChangeSetOut])
def list_change_sets(site_id: uuid.UUID | None = None, status: str | None = None, cursor: str | None = None, limit: int = 50,
                     ctx: Ctx = Depends(get_ctx)) -> Page_[ChangeSetOut]:
    q = select(ChangeSet).join(Site, Site.id == ChangeSet.site_id).where(ctx.site_filter())
    if site_id:
        ctx.site(site_id)
        q = q.where(ChangeSet.site_id == site_id)
    if status:
        q = q.where(ChangeSet.status.in_(status.split(",")))
    rows, nxt = paginate(ctx.db, q, ChangeSet, cursor, limit)
    return Page_[ChangeSetOut](items=[ChangeSetOut.model_validate(c) for c in rows], next_cursor=nxt)


@router.get("/change-sets/{change_id}", response_model=ChangeSetDetail)
def get_change_set(change_id: uuid.UUID, ctx: Ctx = Depends(get_ctx)) -> ChangeSetDetail:
    return _detail(ctx, _load(ctx, change_id))


@router.post("/change-sets/{change_id}/validate", response_model=ChangeSetDetail,
             summary="Re-run validation + policy; optionally revise the value (creates a new immutable version)")
def validate(change_id: uuid.UUID, body: ValidateIn | None = None, ctx: Ctx = Depends(get_ctx)) -> ChangeSetDetail:
    cs = _load(ctx, change_id, "change:propose")
    if body and body.value:
        changes.revise(ctx.db, cs, actor=ctx.actor, value=body.value, rationale=body.rationale)
    else:
        changes.revalidate(ctx.db, cs, ctx.actor)
    return _detail(ctx, cs)


@router.post("/change-sets/{change_id}/approve", response_model=ChangeSetDetail, summary="Approve the exact patch version (hash-bound)")
def approve(change_id: uuid.UUID, body: DecisionIn, ctx: Ctx = Depends(get_ctx),
            idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")) -> JSONResponse:
    cs = _load(ctx, change_id, "change:approve")

    def go() -> tuple[int, Any]:
        changes.approve(ctx.db, cs, actor=ctx.actor, patch_hash_value=body.patch_hash, reason=body.reason)
        return 200, _detail(ctx, cs).model_dump(mode="json")

    status, payload = idempotent(ctx, idempotency_key, {"approve": str(change_id), **body.model_dump()}, go)
    return JSONResponse(payload, status_code=status)


@router.post("/change-sets/{change_id}/reject", response_model=ChangeSetDetail)
def reject(change_id: uuid.UUID, body: RejectIn, ctx: Ctx = Depends(get_ctx)) -> ChangeSetDetail:
    cs = _load(ctx, change_id, "change:approve")
    changes.reject(ctx.db, cs, actor=ctx.actor, patch_hash_value=body.patch_hash, reason=body.reason)
    return _detail(ctx, cs)


@router.post("/change-sets/{change_id}/execute", status_code=202, response_model=ExecutionOut,
             summary="Queue execution of the approved patch (no patch content accepted)")
def execute(change_id: uuid.UUID, body: ExecuteIn, ctx: Ctx = Depends(get_ctx),
            idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")) -> JSONResponse:
    cs = _load(ctx, change_id, "change:execute")
    key = idempotency_key or f"exec:{change_id}:{body.patch_hash}"
    run = changes.execute(ctx.db, cs, actor=ctx.actor, patch_hash_value=body.patch_hash, idempotency_key=key)
    return JSONResponse(ExecutionOut.model_validate(run).model_dump(mode="json"), status_code=202,
                        headers={"location": f"/api/v1/executions/{run.id}"})


@router.post("/change-sets/{change_id}/rollback", status_code=202, response_model=ExecutionOut)
def rollback(change_id: uuid.UUID, body: RollbackIn | None = None, ctx: Ctx = Depends(get_ctx),
             idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")) -> JSONResponse:
    cs = _load(ctx, change_id, "change:rollback")
    key = idempotency_key or f"rollback:{change_id}:{uuid.uuid4()}"
    run = changes.rollback(ctx.db, cs, actor=ctx.actor, idempotency_key=key, reason=body.reason if body else None)
    return JSONResponse(ExecutionOut.model_validate(run).model_dump(mode="json"), status_code=202)


@router.post("/change-sets/{change_id}/cancel", response_model=ChangeSetDetail)
def cancel(change_id: uuid.UUID, ctx: Ctx = Depends(get_ctx)) -> ChangeSetDetail:
    cs = _load(ctx, change_id, "change:execute")
    changes.cancel(ctx.db, cs, ctx.actor)
    return _detail(ctx, cs)


@router.get("/executions/{execution_id}", response_model=ExecutionOut)
def get_execution(execution_id: uuid.UUID, ctx: Ctx = Depends(get_ctx)) -> ExecutionOut:
    run = ctx.db.get(ExecutionRun, execution_id)
    if run is None:
        raise NotFound("Execution not found")
    _load(ctx, run.change_set_id)
    return ExecutionOut.model_validate(run)


# ------------------------------------------------------------------ plans / copilot / workflows


@router.post("/sites/{site_id}/plans", status_code=202, summary="Ask the Strategy Agent for a prioritised plan")
def create_plan(site_id: uuid.UUID, ctx: Ctx = Depends(get_ctx)) -> JSONResponse:
    site = ctx.site(site_id, "plan:create")
    wf = WorkflowRun(tenant_id=ctx.tenant.id, site_id=site.id, kind="strategy_plan", status="queued", trigger="manual")
    ctx.db.add(wf)
    ctx.db.flush()
    outbox.enqueue(ctx.db, "agents.plan", {"workflow_run_id": str(wf.id), "user_id": str(ctx.user.id)}, tenant_id=ctx.tenant.id,
                   dedupe_key=f"plan:{wf.id}")
    return JSONResponse({"id": str(wf.id), "status": "queued", "status_url": f"/api/v1/workflows/{wf.id}"}, status_code=202)


@outbox.handler("agents.plan")
def _h_plan(payload: dict[str, Any], tenant_id: uuid.UUID | None) -> None:
    from aseo.core.db import tenant_session
    from aseo.models.base import utcnow

    with tenant_session(tenant_id) as db:  # type: ignore[arg-type]
        wf = db.get(WorkflowRun, uuid.UUID(payload["workflow_run_id"]))
        site = db.get(Site, wf.site_id)
        wf.status, wf.started_at = "running", utcnow()
        run, plan = agents.strategy_agent(db, site, workflow_run_id=wf.id, created_by=uuid.UUID(payload["user_id"]))
        wf.steps = [{"name": "strategy", "status": "succeeded", "agent_run_id": str(run.id), "plan_id": str(plan.id)}]
        wf.state = {"plan_id": str(plan.id)}
        wf.status, wf.finished_at = "completed", utcnow()


@router.get("/sites/{site_id}/plans")
def list_plans(site_id: uuid.UUID, ctx: Ctx = Depends(get_ctx)) -> list[dict[str, Any]]:
    site = ctx.site(site_id)
    plans = ctx.db.execute(select(ActionPlan).where(ActionPlan.site_id == site.id).order_by(ActionPlan.created_at.desc()).limit(10)).scalars()
    return [{"id": str(p.id), "title": p.title, "summary": p.summary, "created_at": p.created_at.isoformat()} for p in plans]


@router.get("/plans/{plan_id}")
def get_plan(plan_id: uuid.UUID, ctx: Ctx = Depends(get_ctx)) -> dict[str, Any]:
    plan = ctx.db.get(ActionPlan, plan_id)
    if plan is None:
        raise NotFound("Plan not found")
    ctx.site(plan.site_id)
    items = ctx.db.execute(select(PlanItem).where(PlanItem.plan_id == plan.id).order_by(PlanItem.priority)).scalars()
    run = ctx.db.get(AgentRun, plan.agent_run_id) if plan.agent_run_id else None
    return {"id": str(plan.id), "site_id": str(plan.site_id), "title": plan.title, "summary": plan.summary, "goals": plan.goals,
            "created_at": plan.created_at.isoformat(),
            "agent": {"provider": run.provider, "model": run.model, "prompt_version": run.prompt_version,
                      "note": (run.output or {}).get("_meta", {}).get("note")} if run else None,
            "items": [{"id": str(i.id), "finding_id": str(i.finding_id) if i.finding_id else None, "action_type": i.action_type,
                       "title": i.title, "rationale": i.rationale, "priority": i.priority, "impact": i.impact, "effort": i.effort,
                       "evidence_ids": i.evidence_ids, "status": i.status} for i in items]}


@router.post("/copilot/messages", summary="Grounded Q&A over one site's evidence")
def copilot_message(body: CopilotIn, ctx: Ctx = Depends(get_ctx)) -> dict[str, Any]:
    site = ctx.site(body.site_id, "copilot:use")
    run, answer = agents.copilot(ctx.db, site, question=body.message)
    meta = (run.output or {}).get("_meta", {})
    return {"answer": answer.model_dump(), "agent_run_id": str(run.id), "provider": run.provider, "model": run.model,
            "fallback_used": meta.get("fallback_used"), "note": meta.get("note"), "credits_charged": run.credits_charged}


@router.get("/workflows/{workflow_id}")
def get_workflow(workflow_id: uuid.UUID, ctx: Ctx = Depends(get_ctx)) -> dict[str, Any]:
    wf = ctx.db.get(WorkflowRun, workflow_id)
    if wf is None or wf.site_id is None:
        raise NotFound("Workflow not found")
    ctx.site(wf.site_id)
    return _wf_out(ctx, wf)


def _wf_out(ctx: Ctx, wf: WorkflowRun) -> dict[str, Any]:
    runs = ctx.db.execute(select(AgentRun).where(AgentRun.workflow_run_id == wf.id).order_by(AgentRun.created_at)).scalars()
    return {"id": str(wf.id), "kind": wf.kind, "status": wf.status, "trigger": wf.trigger, "current_step": wf.current_step,
            "steps": wf.steps, "state": wf.state, "error": wf.error, "created_at": wf.created_at.isoformat(),
            "finished_at": wf.finished_at.isoformat() if wf.finished_at else None,
            "agent_runs": [_run_out(r) for r in runs]}


def _run_out(r: AgentRun) -> dict[str, Any]:
    return {"id": str(r.id), "agent": r.agent, "task": r.task, "status": r.status, "provider": r.provider, "model": r.model,
            "prompt_version": r.prompt_version, "input_tokens": r.input_tokens, "output_tokens": r.output_tokens,
            "cost_usd": float(r.cost_usd or 0), "credits": r.credits_charged, "latency_ms": r.latency_ms,
            "evidence_ids": r.evidence_ids, "created_at": r.created_at.isoformat(),
            "note": (r.output or {}).get("_meta", {}).get("note") if r.output else None}


@router.get("/sites/{site_id}/workflows")
def list_workflows(site_id: uuid.UUID, ctx: Ctx = Depends(get_ctx)) -> list[dict[str, Any]]:
    site = ctx.site(site_id)
    rows = ctx.db.execute(select(WorkflowRun).where(WorkflowRun.site_id == site.id).order_by(WorkflowRun.created_at.desc()).limit(25)).scalars()
    return [_wf_out(ctx, w) for w in rows]


@router.get("/agent-runs/{run_id}")
def get_agent_run(run_id: uuid.UUID, ctx: Ctx = Depends(get_ctx)) -> dict[str, Any]:
    r = ctx.db.get(AgentRun, run_id)
    if r is None or r.site_id is None:
        raise NotFound("Agent run not found")
    ctx.site(r.site_id)
    tools = ctx.db.execute(select(ToolInvocation).where(ToolInvocation.agent_run_id == r.id).order_by(ToolInvocation.created_at)).scalars()
    return {**_run_out(r), "input": r.input, "output": r.output,
            "tools": [{"tool": t.tool, "args": t.args, "status": t.status, "duration_ms": t.duration_ms, "result": t.result_summary} for t in tools]}


@router.post("/sites/{site_id}/agents/audit", summary="Run the Audit Agent now")
def run_audit_agent(site_id: uuid.UUID, ctx: Ctx = Depends(get_ctx)) -> dict[str, Any]:
    site = ctx.site(site_id, "finding:manage")
    run = agents.audit_agent(ctx.db, site)
    return _run_out(run) | {"output": run.output}


@router.get("/sites/{site_id}/agents/latest-audit")
def latest_audit(site_id: uuid.UUID, ctx: Ctx = Depends(get_ctx)) -> dict[str, Any] | None:
    site = ctx.site(site_id)
    r = ctx.db.execute(select(AgentRun).where(AgentRun.site_id == site.id, AgentRun.agent == "audit", AgentRun.status == "succeeded")
                       .order_by(AgentRun.created_at.desc()).limit(1)).scalar_one_or_none()
    return (_run_out(r) | {"output": r.output}) if r else None


_ = ValidationFailed
