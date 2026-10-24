"""Change sets: finding -> proposal -> validation -> immutable patch -> policy -> approval ->
queued execution -> connector write -> verification -> completed/failed -> rollback.

Invariants enforced here (and covered by tests):
* Patch content lives only in immutable ``patch_versions`` rows; a revision creates a new
  version and every prior approval stops applying (approvals bind to version id + hash).
* ``execute`` never accepts patch content — only the change id, the hash the caller
  approved, and an idempotency key.
* Execution re-checks kill switch, policy, approval binding and the live resource version
  (optimistic concurrency) before writing.
* Verification re-reads the resource and the public HTML; we never report success without it.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from aseo.connectors.base import StaleResourceError
from aseo.connectors.registry import get_connector
from aseo.core.config import get_settings
from aseo.core.db import tenant_session
from aseo.core.errors import AppError, Conflict, ConnectorError, KillSwitchEngaged, NotFound, PolicyDenied, ValidationFailed
from aseo.core.security import sha256_hex
from aseo.models import (
    Approval,
    AutomationPolicy,
    ChangeSet,
    Connector,
    ExecutionRun,
    FindingOccurrence,
    MeasurementAnnotation,
    Page,
    PatchVersion,
    RollbackSnapshot,
    SeoFinding,
    Site,
    Tenant,
)
from aseo.models.base import utcnow
from aseo.services import audit, notifications, outbox
from aseo.services import connectors as connector_svc
from aseo.services import policy as policy_engine
from aseo.services.locks import resource_lock
from aseo.services.validation import validate_value

log = logging.getLogger("aseo.changes")

EXECUTABLE_FROM = {"approved", "failed"}
ROLLBACK_FROM = {"completed", "verification_failed", "verifying"}


@dataclass
class Actor:
    kind: str  # user|system|agent
    id: uuid.UUID | None
    label: str
    ip: str | None = None


SYSTEM = Actor("system", None, "Lodestar automation")


def patch_hash(change_set_id: uuid.UUID, version: int, site_id: uuid.UUID, patch: dict[str, Any]) -> str:
    body = {"change_set_id": str(change_set_id), "version": version, "site_id": str(site_id), "patch": patch}
    return sha256_hex(json.dumps(body, sort_keys=True, separators=(",", ":"), default=str))


def _audit(db: Session, cs: ChangeSet, actor: Actor, action: str, data: dict[str, Any] | None = None) -> None:
    audit.record(db, tenant_id=cs.tenant_id, action=action, actor_type=actor.kind, actor_id=actor.id, actor_label=actor.label,
                 target_type="change_set", target_id=cs.id, site_id=cs.site_id, data=data or {}, ip=actor.ip)


def ensure_policy(db: Session, site: Site) -> AutomationPolicy:
    pol = db.execute(select(AutomationPolicy).where(AutomationPolicy.site_id == site.id)).scalar_one_or_none()
    if pol is None:
        pol = AutomationPolicy(tenant_id=site.tenant_id, site_id=site.id, mode="assist", auto_actions=[], path_scope=[])
        db.add(pol)
        db.flush()
    return pol


def current_version(db: Session, cs: ChangeSet) -> PatchVersion:
    if cs.current_version_id is None:
        raise Conflict("Change set has no patch version.")
    v = db.get(PatchVersion, cs.current_version_id)
    assert v is not None
    return v


def _new_version(db: Session, cs: ChangeSet, patch: dict[str, Any], *, before: dict[str, Any], resource_version: str | None,
                 actor: Actor, rationale: str | None, evidence_ids: list[str]) -> PatchVersion:
    number = (db.execute(select(func.max(PatchVersion.version)).where(PatchVersion.change_set_id == cs.id)).scalar_one() or 0) + 1
    full_patch = {**patch, "before": before, "resource_version": resource_version}
    pv = PatchVersion(
        tenant_id=cs.tenant_id, change_set_id=cs.id, version=number, patch=full_patch, before=before,
        resource_version=resource_version, patch_hash=patch_hash(cs.id, number, cs.site_id, full_patch),
        created_by=actor.id if actor.kind == "user" else None, rationale=rationale, evidence_ids=evidence_ids,
    )
    db.add(pv)
    db.flush()
    cs.current_version_id = pv.id
    return pv


def _policy_input(db: Session, cs: ChangeSet, site: Site, pv: PatchVersion, validation_passed: bool) -> policy_engine.PolicyInput:
    tenant = db.get(Tenant, site.tenant_id)
    pol = ensure_policy(db, site)
    connector = db.get(Connector, cs.connector_id) if cs.connector_id else None
    cap = connector_svc.capability_for(db, connector, cs.action_type)
    url = pv.patch.get("resource", {}).get("url") or site.base_url
    path = urlsplit(url).path or "/"
    start_of_day = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    auto_today = db.execute(
        select(func.count()).select_from(Approval).where(Approval.site_id == site.id, Approval.decision == "auto_approved",
                                                         Approval.created_at >= start_of_day)
    ).scalar_one()
    before_value = (pv.before or {}).get(cs.action_type)
    settings = get_settings()
    return policy_engine.PolicyInput(
        action_type=cs.action_type, url_path=path, is_homepage=path == "/", replaces_existing_value=bool(before_value),
        bulk_size=1, capability_supported=bool(cap and cap.supported), write_mode=cap.write_mode if cap else "none",
        rollback_supported=bool(cap and cap.rollback_supported), site_verified=site.verified_at is not None,
        connector_connected=bool(connector and connector.status == "connected"),
        kill_switch=bool(tenant and tenant.kill_switch) or settings_kill_switch(), mode=pol.mode, paused=pol.paused,
        auto_actions=list(pol.auto_actions or []), path_scope=list(pol.path_scope or []), max_risk_score=pol.max_risk_score,
        max_auto_changes_per_day=pol.max_auto_changes_per_day, auto_changes_today=auto_today,
        validation_passed=validation_passed, connector_mode=connector.mode if connector else "live",
        production=settings.environment == "production",
    )


def settings_kill_switch() -> bool:
    import os

    return os.environ.get("GLOBAL_KILL_SWITCH", "").lower() in ("1", "true", "yes")


def _evaluate(db: Session, cs: ChangeSet, actor: Actor) -> policy_engine.PolicyDecision:
    site = db.get(Site, cs.site_id)
    assert site is not None
    pv = current_version(db, cs)
    others = db.execute(
        select(Page.meta_description if cs.action_type == "meta_description" else Page.title).where(Page.site_id == site.id, Page.id != cs.page_id)
    ).scalars().all() if cs.action_type in ("meta_description", "title") else []
    validation = validate_value(cs.action_type, pv.patch["after"][cs.action_type], before=(pv.before or {}).get(cs.action_type),
                                site_values=[v for v in others if v])
    # validation is stored as part of the immutable version's sidecar (not part of the hash)
    pv.validation = validation
    decision = policy_engine.evaluate(_policy_input(db, cs, site, pv, validation["passed"]))
    cs.risk_score = decision.risk_score
    cs.risk_level = decision.risk_level
    cs.policy_decision = {**decision.to_dict(), "evaluated_at": utcnow().isoformat(), "patch_hash": pv.patch_hash}
    if not validation["passed"]:
        cs.status = "invalid"
    elif decision.decision == "deny":
        cs.status = "blocked"
    elif decision.decision == "require_approval":
        cs.status = "pending_approval"
    else:
        cs.status = "approved"
        db.add(Approval(tenant_id=cs.tenant_id, change_set_id=cs.id, patch_version_id=pv.id, patch_hash=pv.patch_hash,
                        site_id=cs.site_id, decision="auto_approved", reason="Autopilot policy: all checks passed",
                        policy_snapshot=cs.policy_decision))
        db.flush()
        _audit(db, cs, SYSTEM, "change_set.auto_approved", {"patch_hash": pv.patch_hash, "risk": decision.risk_score})
    return decision


# ------------------------------------------------------------------ propose / revise


def propose(
    db: Session,
    *,
    actor: Actor,
    site: Site,
    url: str,
    action_type: str,
    value: str,
    finding_id: uuid.UUID | None = None,
    source: str = "user",
    rationale: str | None = None,
    evidence_ids: list[str] | None = None,
    agent_run_id: uuid.UUID | None = None,
) -> ChangeSet:
    page = db.execute(select(Page).where(Page.site_id == site.id, Page.url == url)).scalar_one_or_none()
    connector = connector_svc.write_connector_for(db, site)
    cap = connector_svc.capability_for(db, connector, action_type)
    title = {"meta_description": "Update meta description", "title": "Update SEO title"}.get(action_type, action_type)
    cs = ChangeSet(
        tenant_id=site.tenant_id, site_id=site.id, connector_id=connector.id if connector else None, finding_id=finding_id,
        page_id=page.id if page else None, action_type=action_type, title=f"{title} — {urlsplit(url).path or '/'}",
        source=source, agent_run_id=agent_run_id, created_by=actor.id if actor.kind == "user" else None,
        is_fixture=bool(connector and connector.mode == "fixture"), status="draft",
    )
    db.add(cs)
    db.flush()
    resource: dict[str, Any] = {"type": "url", "id": url, "url": url}
    before = {action_type: (getattr(page, action_type, None) if page else None) or ""}
    resource_version = None
    warnings: list[str] = []
    if connector is not None and cap is not None and cap.supported and connector.status == "connected":
        impl = get_connector(connector.provider)
        ctx = connector_svc.build_context(db, site, connector)
        prepared = connector_svc.run(impl.prepare_patch(ctx, url, action_type, {action_type: value}))
        resource = {**prepared.ref, "url": prepared.ref.get("url") or url}
        before = prepared.before
        resource_version = prepared.resource_version
        warnings = prepared.warnings
    patch = {
        "action_type": action_type,
        "resource": resource,
        "after": {action_type: value.strip()},
        "connector": {"provider": connector.provider if connector else "none", "mode": connector.mode if connector else None},
        "warnings": warnings,
    }
    cs.resource_ref = resource
    pv = _new_version(db, cs, patch, before=before, resource_version=resource_version, actor=actor, rationale=rationale,
                      evidence_ids=evidence_ids or [])
    _audit(db, cs, actor, "change_set.proposed", {"version": pv.version, "patch_hash": pv.patch_hash, "action_type": action_type,
                                                  "url": url, "source": source})
    if connector is None or cap is None or not cap.supported:
        cs.status = "recommendation"
        cs.policy_decision = {"decision": "deny", "reasons": ["No connected platform can perform this change — apply it manually."]}
        return cs
    decision = _evaluate(db, cs, actor)
    if cs.status == "approved":
        _enqueue_execution(db, cs, pv, SYSTEM, idempotency_key=f"auto:{pv.patch_hash}")
    log.info("change proposed", extra={"site_id": str(site.id), "status": cs.status})
    _ = decision
    return cs


def revise(db: Session, cs: ChangeSet, *, actor: Actor, value: str, rationale: str | None = None) -> ChangeSet:
    if cs.status not in ("pending_approval", "invalid", "blocked", "rejected", "failed", "approved"):
        raise Conflict(f"Cannot revise a change in status '{cs.status}'.")
    site = db.get(Site, cs.site_id)
    assert site is not None
    old = current_version(db, cs)
    connector = db.get(Connector, cs.connector_id) if cs.connector_id else None
    before, resource_version, resource = old.before, old.resource_version, old.patch["resource"]
    if connector is not None and connector.status == "connected":
        impl = get_connector(connector.provider)
        prepared = connector_svc.run(impl.prepare_patch(connector_svc.build_context(db, site, connector), resource["url"], cs.action_type,
                                                        {cs.action_type: value}))
        before, resource_version = prepared.before, prepared.resource_version
    patch = {**{k: v for k, v in old.patch.items() if k not in ("before", "resource_version")}, "after": {cs.action_type: value.strip()}}
    pv = _new_version(db, cs, patch, before=before, resource_version=resource_version, actor=actor, rationale=rationale,
                      evidence_ids=old.evidence_ids)
    _audit(db, cs, actor, "change_set.revised", {"version": pv.version, "patch_hash": pv.patch_hash, "previous_hash": old.patch_hash,
                                                 "note": "Previous approvals no longer apply"})
    _evaluate(db, cs, actor)
    if cs.status == "approved":
        _enqueue_execution(db, cs, pv, SYSTEM, idempotency_key=f"auto:{pv.patch_hash}")
    return cs


def revalidate(db: Session, cs: ChangeSet, actor: Actor) -> ChangeSet:
    if cs.status not in ("pending_approval", "invalid", "blocked", "draft"):
        raise Conflict(f"Cannot validate a change in status '{cs.status}'.")
    _evaluate(db, cs, actor)
    _audit(db, cs, actor, "change_set.validated", {"status": cs.status})
    if cs.status == "approved":
        pv = current_version(db, cs)
        _enqueue_execution(db, cs, pv, SYSTEM, idempotency_key=f"auto:{pv.patch_hash}")
    return cs


# ------------------------------------------------------------------ approval


def _require_hash(pv: PatchVersion, supplied: str) -> None:
    if supplied != pv.patch_hash:
        raise Conflict("The patch changed since you reviewed it. Review the current version.", code="patch_hash_mismatch",
                       details={"current_hash": pv.patch_hash})


def approve(db: Session, cs: ChangeSet, *, actor: Actor, patch_hash_value: str, reason: str | None) -> Approval:
    if cs.status != "pending_approval":
        raise Conflict(f"Only changes pending approval can be approved (status: {cs.status}).", code="invalid_state")
    pv = current_version(db, cs)
    _require_hash(pv, patch_hash_value)
    decision = _evaluate(db, cs, actor)  # re-check: kill switch, connector, validation may have changed
    if cs.status in ("blocked", "invalid"):
        raise PolicyDenied("Policy no longer allows this change.", details={"reasons": decision.reasons})
    ap = Approval(tenant_id=cs.tenant_id, change_set_id=cs.id, patch_version_id=pv.id, patch_hash=pv.patch_hash, site_id=cs.site_id,
                  decision="approved", reason=reason, decided_by=actor.id, policy_snapshot=cs.policy_decision or {})
    db.add(ap)
    cs.status = "approved"
    db.flush()
    _audit(db, cs, actor, "change_set.approved", {"patch_hash": pv.patch_hash, "version": pv.version, "reason": reason})
    return ap


def reject(db: Session, cs: ChangeSet, *, actor: Actor, patch_hash_value: str, reason: str) -> Approval:
    if cs.status not in ("pending_approval", "approved"):
        raise Conflict(f"Cannot reject a change in status '{cs.status}'.", code="invalid_state")
    pv = current_version(db, cs)
    _require_hash(pv, patch_hash_value)
    ap = Approval(tenant_id=cs.tenant_id, change_set_id=cs.id, patch_version_id=pv.id, patch_hash=pv.patch_hash, site_id=cs.site_id,
                  decision="rejected", reason=reason, decided_by=actor.id, policy_snapshot=cs.policy_decision or {})
    db.add(ap)
    cs.status = "rejected"
    db.flush()
    _audit(db, cs, actor, "change_set.rejected", {"patch_hash": pv.patch_hash, "reason": reason})
    return ap


def valid_approval(db: Session, cs: ChangeSet, pv: PatchVersion) -> Approval | None:
    ap = db.execute(
        select(Approval).where(Approval.change_set_id == cs.id).order_by(Approval.created_at.desc()).limit(1)
    ).scalar_one_or_none()
    if ap is None or ap.decision not in ("approved", "auto_approved"):
        return None
    if ap.patch_version_id != pv.id or ap.patch_hash != pv.patch_hash:
        return None
    return ap


# ------------------------------------------------------------------ execution


def _enqueue_execution(db: Session, cs: ChangeSet, pv: PatchVersion, actor: Actor, *, idempotency_key: str, kind: str = "apply",
                       approval: Approval | None = None) -> ExecutionRun:
    existing = db.execute(
        select(ExecutionRun).where(ExecutionRun.tenant_id == cs.tenant_id, ExecutionRun.idempotency_key == idempotency_key)
    ).scalar_one_or_none()
    if existing is not None:
        if existing.change_set_id != cs.id:
            raise Conflict("Idempotency key already used for another change.", code="idempotency_key_reused")
        return existing
    connector = db.get(Connector, cs.connector_id) if cs.connector_id else None
    if kind == "apply" and approval is None:
        approval = valid_approval(db, cs, pv)
    run = ExecutionRun(
        tenant_id=cs.tenant_id, change_set_id=cs.id, patch_version_id=pv.id, patch_hash=pv.patch_hash,
        approval_id=approval.id if approval else None,
        kind=kind, status="queued", idempotency_key=idempotency_key, connector_provider=connector.provider if connector else None,
        connector_mode=connector.mode if connector else None, requested_by=actor.id,
    )
    db.add(run)
    db.flush()
    cs.status = "queued" if kind == "apply" else "rollback_queued"
    outbox.enqueue(db, f"execution.{kind}", {"execution_id": str(run.id)}, tenant_id=cs.tenant_id, dedupe_key=f"exec:{run.id}")
    _audit(db, cs, actor, f"execution.{kind}_queued", {"execution_id": str(run.id), "patch_hash": pv.patch_hash})
    return run


def execute(db: Session, cs: ChangeSet, *, actor: Actor, patch_hash_value: str, idempotency_key: str) -> ExecutionRun:
    prior = db.execute(
        select(ExecutionRun).where(ExecutionRun.tenant_id == cs.tenant_id, ExecutionRun.idempotency_key == idempotency_key)
    ).scalar_one_or_none()
    if prior is not None:
        if prior.change_set_id != cs.id or prior.patch_hash != patch_hash_value:
            raise Conflict("Idempotency key already used with different parameters.", code="idempotency_key_reused")
        return prior
    if cs.status not in EXECUTABLE_FROM:
        raise Conflict(f"Change must be approved before execution (status: {cs.status}).", code="not_approved")
    pv = current_version(db, cs)
    _require_hash(pv, patch_hash_value)
    ap = valid_approval(db, cs, pv)
    if ap is None:
        raise PolicyDenied("No valid approval for this exact patch version.", code="approval_missing")
    site = db.get(Site, cs.site_id)
    assert site is not None
    decision = policy_engine.evaluate(_policy_input(db, cs, site, pv, bool((pv.validation or {}).get("passed"))))
    if decision.decision == "deny":
        if any("kill switch" in r.lower() for r in decision.reasons):
            raise KillSwitchEngaged("Emergency kill switch is engaged. No changes can be executed.")
        raise PolicyDenied("Policy denies execution.", details={"reasons": decision.reasons})
    return _enqueue_execution(db, cs, pv, actor, idempotency_key=idempotency_key, approval=ap)


def cancel(db: Session, cs: ChangeSet, actor: Actor) -> None:
    runs = db.execute(select(ExecutionRun).where(ExecutionRun.change_set_id == cs.id, ExecutionRun.status == "queued")).scalars().all()
    if not runs:
        raise Conflict("Nothing queued to cancel (running writes cannot be interrupted safely).")
    for r in runs:
        r.status = "cancelled"
        r.finished_at = utcnow()
    cs.status = "cancelled"
    _audit(db, cs, actor, "execution.cancelled", {"executions": [str(r.id) for r in runs]})


def rollback(db: Session, cs: ChangeSet, *, actor: Actor, idempotency_key: str, reason: str | None = None) -> ExecutionRun:
    prior = db.execute(
        select(ExecutionRun).where(ExecutionRun.tenant_id == cs.tenant_id, ExecutionRun.idempotency_key == idempotency_key)
    ).scalar_one_or_none()
    if prior is not None:
        return prior
    if cs.status not in ROLLBACK_FROM:
        raise Conflict(f"Rollback is not available in status '{cs.status}'.", code="invalid_state")
    snap = db.execute(
        select(RollbackSnapshot).where(RollbackSnapshot.change_set_id == cs.id).order_by(RollbackSnapshot.created_at.desc()).limit(1)
    ).scalar_one_or_none()
    if snap is None or not snap.restorable:
        raise Conflict("No restorable snapshot exists for this change; restore manually.", code="rollback_unavailable")
    connector = db.get(Connector, cs.connector_id) if cs.connector_id else None
    cap = connector_svc.capability_for(db, connector, cs.action_type)
    if not cap or not cap.rollback_supported:
        raise Conflict("This connector cannot roll back automatically. Restore manually.", code="rollback_unsupported")
    tenant = db.get(Tenant, cs.tenant_id)
    if tenant and tenant.kill_switch:
        raise KillSwitchEngaged("Kill switch engaged: rollbacks must be done manually or after disengaging.")
    pv = current_version(db, cs)
    run = _enqueue_execution(db, cs, pv, actor, idempotency_key=idempotency_key, kind="rollback")
    _audit(db, cs, actor, "change_set.rollback_requested", {"reason": reason})
    return run


# ------------------------------------------------------------------ worker handlers


def _finish(run: ExecutionRun, status: str, error: str | None = None) -> None:
    run.status = status
    run.error = error
    run.finished_at = utcnow()


def _mark_finding_fixed(db: Session, cs: ChangeSet) -> None:
    if not cs.finding_id or not cs.page_id:
        return
    occ = db.execute(select(FindingOccurrence).where(FindingOccurrence.finding_id == cs.finding_id,
                                                     FindingOccurrence.page_id == cs.page_id)).scalar_one_or_none()
    if occ:
        occ.status = "fixed"
    remaining = db.execute(select(func.count()).select_from(FindingOccurrence).where(
        FindingOccurrence.finding_id == cs.finding_id, FindingOccurrence.status == "open")).scalar_one()
    finding = db.get(SeoFinding, cs.finding_id)
    if finding:
        finding.affected_count = remaining
        if remaining == 0:
            finding.status = "resolved"


def run_execution(execution_id: uuid.UUID, tenant_id: uuid.UUID) -> None:
    with tenant_session(tenant_id) as db:
        run = db.get(ExecutionRun, execution_id)
        if run is None:
            raise outbox.PermanentJobError("execution not found")
        if run.status not in ("queued", "running", "verifying"):
            return  # duplicate delivery or cancelled
        cs = db.get(ChangeSet, run.change_set_id)
        pv = db.get(PatchVersion, run.patch_version_id)
        site = db.get(Site, cs.site_id) if cs else None
        tenant = db.get(Tenant, tenant_id)
        assert cs and pv and site and tenant
        if tenant.kill_switch or settings_kill_switch():
            _finish(run, "cancelled", "Kill switch engaged before execution")
            cs.status = "cancelled"
            _audit(db, cs, SYSTEM, "execution.cancelled_kill_switch", {"execution_id": str(run.id)})
            return
        if pv.patch_hash != run.patch_hash or cs.current_version_id != pv.id or valid_approval(db, cs, pv) is None:
            _finish(run, "failed", "Approval binding no longer valid (patch changed)")
            cs.status = "pending_approval"
            _audit(db, cs, SYSTEM, "execution.rejected_stale_approval", {"execution_id": str(run.id)})
            return
        resource = pv.patch["resource"]
        lock_key = f"res:{site.id}:{resource.get('type')}:{resource.get('id')}"
    try:
        with resource_lock(lock_key):
            _apply_and_verify(execution_id, tenant_id)
    except Conflict:
        raise outbox.RetryableJobError("resource locked") from None


def _apply_and_verify(execution_id: uuid.UUID, tenant_id: uuid.UUID) -> None:
    with tenant_session(tenant_id) as db:
        run = db.get(ExecutionRun, execution_id)
        assert run is not None
        cs = db.get(ChangeSet, run.change_set_id)
        pv = db.get(PatchVersion, run.patch_version_id)
        site = db.get(Site, cs.site_id)
        connector = db.get(Connector, cs.connector_id) if cs.connector_id else None
        if connector is None:
            _finish(run, "failed", "No connector")
            cs.status = "failed"
            return
        impl = get_connector(connector.provider)
        ctx = connector_svc.build_context(db, site, connector)
        already_applied = bool(run.connector_result.get("applied"))
        run.status = "running"
        run.attempt += 1
        run.started_at = run.started_at or utcnow()
        cs.status = "executing"
        patch = dict(pv.patch)
        field = cs.action_type
        attempt, max_attempts = run.attempt, run.max_attempts
        db.commit()

        try:
            if not already_applied:
                fresh = connector_svc.run(impl.read_resource(ctx, patch["resource"]["url"]))
                if pv.resource_version and fresh.version != pv.resource_version:
                    raise StaleResourceError("Resource changed after the patch was prepared.")
                db.add(RollbackSnapshot(tenant_id=tenant_id, execution_id=run.id, change_set_id=cs.id, resource_ref=patch["resource"],
                                        previous_value={field: fresh.fields.get(field, "")}, resource_version=fresh.version,
                                        restorable=True))
                result = connector_svc.run(impl.apply_patch(ctx, patch, expected_version=pv.resource_version,
                                                            change_ref=f"lodestar:{cs.id}:v{pv.version}"))
                run.connector_result = {"applied": True, "live": result.live, "resource_version": result.resource_version,
                                        "previous": result.previous, "response": result.response, "external_url": result.external_url,
                                        "applied_at": utcnow().isoformat()}
                _audit(db, cs, SYSTEM, "execution.write_applied", {"execution_id": str(run.id), "connector": connector.provider,
                                                                   "mode": connector.mode, "resource_version": result.resource_version})
                if not result.live:
                    run.status = "awaiting_deploy"
                    cs.status = "awaiting_deploy"
                    db.commit()
                    return
            run.status = "verifying"
            cs.status = "verifying"
            db.commit()
            verification = connector_svc.run(impl.verify_patch(ctx, patch, run.connector_result))
        except StaleResourceError as exc:
            _finish(run, "failed", f"stale_resource_version: {exc.message}")
            cs.status = "failed"
            _audit(db, cs, SYSTEM, "execution.failed", {"execution_id": str(run.id), "reason": "stale_resource_version"})
            notifications.notify(db, tenant_id, kind="execution_failed", severity="warning", title="Change not applied: page changed",
                                 body="The page was edited after the patch was prepared. Revise the change to review the latest value.",
                                 link=f"/app/fixes/{cs.id}")
            return
        except ConnectorError as exc:
            if exc.retryable and attempt < max_attempts:
                run.status = "queued"
                run.error = f"attempt {attempt}: {exc.message}"
                cs.status = "queued"
                db.commit()
                raise outbox.RetryableJobError(exc.message) from exc
            _finish(run, "dead_letter" if exc.retryable else "failed", exc.message)
            cs.status = "failed"
            _audit(db, cs, SYSTEM, "execution.failed", {"execution_id": str(run.id), "error": exc.message, "attempts": attempt})
            notifications.notify(db, tenant_id, kind="execution_failed", severity="critical", title="Change execution failed",
                                 body=exc.message, link=f"/app/fixes/{cs.id}")
            return

        _record_verification(db, run, cs, site, verification)


def _record_verification(db: Session, run: ExecutionRun, cs: ChangeSet, site: Site, verification: Any) -> None:
    from dataclasses import asdict

    run.verification = {**asdict(verification), "checked_at": utcnow().isoformat(),
                        "checks": (run.verification or {}).get("checks", 0) + 1}
    if verification.verified:
        _finish(run, "succeeded")
        cs.status = "completed"
        _mark_finding_fixed(db, cs)
        db.add(MeasurementAnnotation(tenant_id=cs.tenant_id, site_id=site.id, date=utcnow().date(), kind="change",
                                     title=cs.title, change_set_id=cs.id, execution_id=run.id))
        _audit(db, cs, SYSTEM, "execution.verified", {"execution_id": str(run.id), "method": verification.method})
        notifications.notify(db, cs.tenant_id, kind="execution_succeeded", severity="success", title="Change verified live",
                             body=cs.title, link=f"/app/fixes/{cs.id}")
        outbox.enqueue(db, "measurement.after_change", {"change_set_id": str(cs.id)}, tenant_id=cs.tenant_id,
                       dedupe_key=f"measure:{cs.id}:{run.id}", delay_seconds=5)
    elif verification.pending and run.verification["checks"] < 6:
        run.status = "verifying"
        cs.status = "verifying"
        outbox.enqueue(db, "execution.verify", {"execution_id": str(run.id)}, tenant_id=cs.tenant_id,
                       dedupe_key=f"verify:{run.id}:{run.verification['checks']}", delay_seconds=15 * run.verification["checks"])
        _audit(db, cs, SYSTEM, "execution.verification_pending", {"execution_id": str(run.id), "details": verification.details})
    else:
        _finish(run, "failed", "Verification did not observe the expected value")
        cs.status = "verification_failed"
        _audit(db, cs, SYSTEM, "execution.verification_failed", {"execution_id": str(run.id), "details": verification.details})
        notifications.notify(db, cs.tenant_id, kind="verification_failed", severity="warning", title="Write applied but not verified live",
                             body="Rollback is available.", link=f"/app/fixes/{cs.id}")


def run_verify(execution_id: uuid.UUID, tenant_id: uuid.UUID) -> None:
    with tenant_session(tenant_id) as db:
        run = db.get(ExecutionRun, execution_id)
        if run is None or run.status not in ("verifying", "awaiting_deploy"):
            return
        cs = db.get(ChangeSet, run.change_set_id)
        pv = db.get(PatchVersion, run.patch_version_id)
        site = db.get(Site, cs.site_id)
        connector = db.get(Connector, cs.connector_id)
        impl = get_connector(connector.provider)
        verification = connector_svc.run(impl.verify_patch(connector_svc.build_context(db, site, connector), dict(pv.patch),
                                                            run.connector_result))
        if run.status == "awaiting_deploy" and verification.pending:
            run.verification = {**(run.verification or {}), "last": verification.details, "checked_at": utcnow().isoformat()}
            return
        _record_verification(db, run, cs, site, verification)


def run_rollback(execution_id: uuid.UUID, tenant_id: uuid.UUID) -> None:
    with tenant_session(tenant_id) as db:
        run = db.get(ExecutionRun, execution_id)
        if run is None or run.status not in ("queued", "running"):
            return
        cs = db.get(ChangeSet, run.change_set_id)
        pv = db.get(PatchVersion, run.patch_version_id)
        site = db.get(Site, cs.site_id)
        connector = db.get(Connector, cs.connector_id)
        snap = db.execute(select(RollbackSnapshot).where(RollbackSnapshot.change_set_id == cs.id)
                          .order_by(RollbackSnapshot.created_at.desc()).limit(1)).scalar_one()
        applied = db.execute(select(ExecutionRun).where(ExecutionRun.change_set_id == cs.id, ExecutionRun.kind == "apply",
                                                        ExecutionRun.status.in_(["succeeded", "failed", "verifying"]))
                             .order_by(ExecutionRun.created_at.desc()).limit(1)).scalar_one_or_none()
        current_version = (applied.connector_result or {}).get("resource_version") if applied else None
        run.status = "running"
        run.attempt += 1
        run.started_at = utcnow()
        impl = get_connector(connector.provider)
        ctx = connector_svc.build_context(db, site, connector)
        patch = dict(pv.patch)
        snapshot = {"previous_value": snap.previous_value, "resource_version": snap.resource_version}
        lock_key = f"res:{site.id}:{patch['resource'].get('type')}:{patch['resource'].get('id')}"
        db.commit()
        try:
            with resource_lock(lock_key):
                result = connector_svc.run(impl.rollback(ctx, patch, snapshot, current_version=current_version,
                                                         change_ref=f"lodestar:{cs.id}:rollback"))
                verification = None
                if result.restored:
                    restore_patch = {**patch, "after": snap.previous_value}
                    verification = connector_svc.run(impl.verify_patch(ctx, restore_patch, {}))
        except ConnectorError as exc:
            if exc.retryable and run.attempt < run.max_attempts:
                run.status = "queued"
                db.commit()
                raise outbox.RetryableJobError(exc.message) from exc
            _finish(run, "failed", exc.message)
            cs.status = "rollback_failed"
            _audit(db, cs, SYSTEM, "rollback.failed", {"execution_id": str(run.id), "error": exc.message})
            return
        run.connector_result = {"restored": result.restored, "requires_human": result.requires_human, "message": result.message,
                                "response": result.response, "resource_version": result.resource_version}
        if result.restored:
            from dataclasses import asdict

            run.verification = asdict(verification) if verification else {}
            snap.restored_at = utcnow()
            ok = bool(verification and (verification.verified or verification.pending))
            _finish(run, "succeeded" if ok else "failed", None if ok else "Restore written but not observed live yet")
            cs.status = "rolled_back"
            if cs.finding_id and cs.page_id:
                occ = db.execute(select(FindingOccurrence).where(FindingOccurrence.finding_id == cs.finding_id,
                                                                 FindingOccurrence.page_id == cs.page_id)).scalar_one_or_none()
                if occ:
                    occ.status = "open"
                finding = db.get(SeoFinding, cs.finding_id)
                if finding and finding.status == "resolved":
                    finding.status = "open"
                    finding.affected_count += 1
            db.add(MeasurementAnnotation(tenant_id=cs.tenant_id, site_id=site.id, date=utcnow().date(), kind="rollback",
                                         title=f"Rolled back: {cs.title}", change_set_id=cs.id, execution_id=run.id))
            _audit(db, cs, SYSTEM, "rollback.completed", {"execution_id": str(run.id), "verified": ok})
        else:
            _finish(run, "failed", result.message)
            cs.status = "rollback_failed"
            _audit(db, cs, SYSTEM, "rollback.requires_human", {"execution_id": str(run.id), "message": result.message})
            notifications.notify(db, cs.tenant_id, kind="rollback_failed", severity="critical", title="Rollback needs manual action",
                                 body=result.message, link=f"/app/fixes/{cs.id}")


@outbox.handler("execution.apply")
def _h_apply(payload: dict[str, Any], tenant_id: uuid.UUID | None) -> None:
    assert tenant_id
    run_execution(uuid.UUID(payload["execution_id"]), tenant_id)


@outbox.handler("execution.verify")
def _h_verify(payload: dict[str, Any], tenant_id: uuid.UUID | None) -> None:
    assert tenant_id
    run_verify(uuid.UUID(payload["execution_id"]), tenant_id)


@outbox.handler("execution.rollback")
def _h_rollback(payload: dict[str, Any], tenant_id: uuid.UUID | None) -> None:
    assert tenant_id
    run_rollback(uuid.UUID(payload["execution_id"]), tenant_id)


def get_change(db: Session, change_id: uuid.UUID) -> ChangeSet:
    cs = db.get(ChangeSet, change_id)
    if cs is None:
        raise NotFound("Change set not found")
    return cs


def kill_switch(db: Session, tenant: Tenant, *, engaged: bool, actor: Actor) -> int:
    tenant.kill_switch = engaged
    cancelled = 0
    if engaged:
        runs = db.execute(select(ExecutionRun).where(ExecutionRun.tenant_id == tenant.id, ExecutionRun.status == "queued")).scalars().all()
        for r in runs:
            _finish(r, "cancelled", "Kill switch engaged")
            cs = db.get(ChangeSet, r.change_set_id)
            if cs:
                cs.status = "cancelled"
            cancelled += 1
    audit.record(db, tenant_id=tenant.id, action="kill_switch.engaged" if engaged else "kill_switch.released", actor_type=actor.kind,
                 actor_id=actor.id, actor_label=actor.label, target_type="tenant", target_id=tenant.id, data={"cancelled": cancelled})
    return cancelled


_ = (AppError, ValidationFailed, timedelta)
