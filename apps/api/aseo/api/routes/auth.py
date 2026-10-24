from __future__ import annotations

import json
import uuid
from datetime import timedelta

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from aseo.api.deps import Ctx, client_ip, get_ctx, get_db, get_user_session, require
from aseo.api.schemas import (
    LoginIn,
    MemberIn,
    MemberOut,
    MembershipOut,
    OrgCreateIn,
    OrgOut,
    OrgUpdateIn,
    RegisterIn,
    SessionOut,
    UserOut,
    WorkspaceIn,
    WorkspaceOut,
)
from aseo.core.config import get_settings
from aseo.core.db import set_session_tenant
from aseo.core.errors import Conflict, NotFound, ValidationFailed
from aseo.models import (
    AuditEvent,
    ChangeSet,
    ClientWorkspace,
    Membership,
    SeoFinding,
    Site,
    Tenant,
    User,
    UserSession,
    WorkspaceMembership,
)
from aseo.models.base import utcnow
from aseo.services import audit, rbac, tenancy
from aseo.services.changes import kill_switch

router = APIRouter(tags=["auth & organizations"])


def _set_cookies(response: Response, token: str, csrf: str) -> None:
    s = get_settings()
    max_age = s.session_ttl_hours * 3600
    response.set_cookie(s.session_cookie_name, token, httponly=True, secure=s.cookie_secure, samesite="lax", max_age=max_age, path="/")
    response.set_cookie(s.csrf_cookie_name, csrf, httponly=False, secure=s.cookie_secure, samesite="lax", max_age=max_age, path="/")


def _session_out(db: Session, user: User, sess: UserSession, token: str | None = None) -> SessionOut:
    memberships = db.execute(select(Membership, Tenant).join(Tenant, Tenant.id == Membership.tenant_id)
                             .where(Membership.user_id == user.id).order_by(Membership.created_at)).all()
    org, role = None, None
    for m, t in memberships:
        if t.id == sess.active_tenant_id:
            org, role = t, m.role
    return SessionOut(
        user=UserOut.model_validate(user),
        organization=OrgOut.model_validate(org) if org else None,
        role=role,
        permissions=rbac.permissions_for(role) if role else [],
        memberships=[MembershipOut(organization=OrgOut.model_validate(t), role=m.role) for m, t in memberships],
        csrf_token=sess.csrf_token,
        token=token,
    )


@router.post("/auth/register", response_model=SessionOut, status_code=201, summary="Create an account (and optionally an organization)")
def register(body: RegisterIn, request: Request, response: Response, db: Session = Depends(get_db)) -> SessionOut:
    user = tenancy.create_user(db, email=body.email, name=body.name, password=body.password)
    if body.organization_name:
        tenancy.create_organization(db, owner=user, name=body.organization_name, kind=body.organization_kind)
    token, sess = tenancy.start_session(db, user, ip=client_ip(request), user_agent=request.headers.get("user-agent"))
    _set_cookies(response, token, sess.csrf_token)
    return _session_out(db, user, sess, token)


@router.post("/auth/login", response_model=SessionOut, summary="Sign in")
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)) -> SessionOut:
    user = tenancy.authenticate(db, body.email, body.password)
    token, sess = tenancy.start_session(db, user, ip=client_ip(request), user_agent=request.headers.get("user-agent"))
    if sess.active_tenant_id:
        set_session_tenant(db, sess.active_tenant_id)
        audit.record(db, tenant_id=sess.active_tenant_id, action="auth.login", actor_id=user.id, actor_label=user.email,
                     target_type="user", target_id=user.id, ip=client_ip(request))
    _set_cookies(response, token, sess.csrf_token)
    return _session_out(db, user, sess, token)


@router.post("/auth/logout", status_code=204, summary="Sign out")
def logout(response: Response, us: tuple[User, UserSession] = Depends(get_user_session)) -> Response:
    _, sess = us
    sess.revoked_at = utcnow()
    s = get_settings()
    response.delete_cookie(s.session_cookie_name, path="/")
    response.delete_cookie(s.csrf_cookie_name, path="/")
    response.status_code = 204
    return response


@router.get("/auth/me", response_model=SessionOut, summary="Current session")
def me(us: tuple[User, UserSession] = Depends(get_user_session), db: Session = Depends(get_db)) -> SessionOut:
    user, sess = us
    return _session_out(db, user, sess)


@router.post("/auth/switch-organization/{organization_id}", response_model=SessionOut)
def switch_org(organization_id: uuid.UUID, us: tuple[User, UserSession] = Depends(get_user_session),
               db: Session = Depends(get_db)) -> SessionOut:
    user, sess = us
    tenancy.switch_tenant(db, sess, organization_id)
    return _session_out(db, user, sess)


@router.post("/organizations", response_model=OrgOut, status_code=201, summary="Create an organization (business or agency)")
def create_org(body: OrgCreateIn, us: tuple[User, UserSession] = Depends(get_user_session), db: Session = Depends(get_db)) -> OrgOut:
    user, sess = us
    tenant, _ = tenancy.create_organization(db, owner=user, name=body.name, kind=body.kind, locale=body.locale, timezone=body.timezone)
    sess.active_tenant_id = tenant.id
    return OrgOut.model_validate(tenant)


@router.get("/organizations/current", response_model=OrgOut)
def current_org(ctx: Ctx = Depends(get_ctx)) -> OrgOut:
    return OrgOut.model_validate(ctx.tenant)


@router.patch("/organizations/current", response_model=OrgOut)
def update_org(body: OrgUpdateIn, ctx: Ctx = Depends(require("org:manage"))) -> OrgOut:
    data = body.model_dump(exclude_none=True)
    for k, v in data.items():
        setattr(ctx.tenant, k, v)
    audit.record(ctx.db, tenant_id=ctx.tenant.id, action="organization.updated", actor_id=ctx.user.id, actor_label=ctx.user.email,
                 target_type="tenant", target_id=ctx.tenant.id, data={"fields": sorted(data)})
    return OrgOut.model_validate(ctx.tenant)


@router.post("/organizations/current/kill-switch", summary="Engage or release the emergency kill switch")
def toggle_kill_switch(engaged: bool, ctx: Ctx = Depends(require("killswitch:toggle"))) -> dict[str, object]:
    cancelled = kill_switch(ctx.db, ctx.tenant, engaged=engaged, actor=ctx.actor)
    return {"kill_switch": ctx.tenant.kill_switch, "cancelled_executions": cancelled}


@router.get("/organizations/current/members", response_model=list[MemberOut])
def members(ctx: Ctx = Depends(require("org:read"))) -> list[MemberOut]:
    rows = ctx.db.execute(select(Membership, User).join(User, User.id == Membership.user_id).where(Membership.tenant_id == ctx.tenant.id)).all()
    out = []
    for m, u in rows:
        ws = list(ctx.db.execute(select(WorkspaceMembership.workspace_id).where(WorkspaceMembership.user_id == u.id)).scalars())
        out.append(MemberOut(user_id=u.id, email=u.email, name=u.name, role=m.role, workspaces=ws))
    return out


@router.post("/organizations/current/members", response_model=MemberOut, status_code=201)
def add_member(body: MemberIn, ctx: Ctx = Depends(require("members:manage"))) -> MemberOut:
    if body.role == "admin" and ctx.role != "owner":
        raise ValidationFailed("Only owners can add admins.")
    user = ctx.db.execute(select(User).where(User.email == body.email.lower())).scalar_one_or_none()
    if user is None:
        if not body.password:
            raise ValidationFailed("Provide an initial password for a new user.")
        user = tenancy.create_user(ctx.db, email=body.email, name=body.name, password=body.password)
    if ctx.db.execute(select(Membership).where(Membership.tenant_id == ctx.tenant.id, Membership.user_id == user.id)).scalar_one_or_none():
        raise Conflict("Already a member.")
    ctx.db.add(Membership(tenant_id=ctx.tenant.id, user_id=user.id, role=body.role))
    for wid in body.workspace_ids:
        if ctx.db.get(ClientWorkspace, wid) is None:
            raise NotFound("Workspace not found")
        ctx.db.add(WorkspaceMembership(tenant_id=ctx.tenant.id, workspace_id=wid, user_id=user.id, role=body.role))
    audit.record(ctx.db, tenant_id=ctx.tenant.id, action="member.added", actor_id=ctx.user.id, actor_label=ctx.user.email,
                 target_type="user", target_id=user.id, data={"role": body.role, "workspaces": [str(w) for w in body.workspace_ids]})
    return MemberOut(user_id=user.id, email=user.email, name=user.name, role=body.role, workspaces=body.workspace_ids)


@router.post("/workspaces", response_model=WorkspaceOut, status_code=201, summary="Create a client workspace")
def create_workspace(body: WorkspaceIn, ctx: Ctx = Depends(require("workspace:manage"))) -> WorkspaceOut:
    slug = tenancy.slugify(body.name)
    if ctx.db.execute(select(ClientWorkspace).where(ClientWorkspace.tenant_id == ctx.tenant.id, ClientWorkspace.slug == slug)).scalar_one_or_none():
        raise Conflict("A workspace with this name already exists.")
    ws = ClientWorkspace(tenant_id=ctx.tenant.id, name=body.name, slug=slug, branding=body.branding, notes=body.notes)
    ctx.db.add(ws)
    ctx.db.flush()
    audit.record(ctx.db, tenant_id=ctx.tenant.id, action="workspace.created", actor_id=ctx.user.id, actor_label=ctx.user.email,
                 target_type="workspace", target_id=ws.id, data={"name": ws.name})
    return WorkspaceOut.model_validate(ws)


@router.get("/workspaces", response_model=list[WorkspaceOut])
def list_workspaces(ctx: Ctx = Depends(require("workspace:read"))) -> list[WorkspaceOut]:
    q = select(ClientWorkspace).where(ClientWorkspace.tenant_id == ctx.tenant.id)
    if ctx.workspace_ids is not None:
        q = q.where(ClientWorkspace.id.in_(ctx.workspace_ids))
    return [WorkspaceOut.model_validate(w) for w in ctx.db.execute(q.order_by(ClientWorkspace.created_at)).scalars()]


@router.post("/organizations/current/export", summary="Export organization data (JSON)")
def export_data(ctx: Ctx = Depends(require("settings:manage"))) -> Response:
    db = ctx.db
    sites = db.execute(select(Site).where(Site.tenant_id == ctx.tenant.id)).scalars().all()
    payload = {
        "organization": OrgOut.model_validate(ctx.tenant).model_dump(mode="json"),
        "sites": [{"id": str(s.id), "domain": s.domain, "platform": s.platform, "health_score": s.health_score} for s in sites],
        "findings": [{"site_id": str(f.site_id), "rule": f.rule_key, "status": f.status, "affected": f.affected_count}
                     for f in db.execute(select(SeoFinding).where(SeoFinding.tenant_id == ctx.tenant.id)).scalars()],
        "change_sets": [{"id": str(c.id), "title": c.title, "status": c.status, "created_at": c.created_at.isoformat()}
                        for c in db.execute(select(ChangeSet).where(ChangeSet.tenant_id == ctx.tenant.id)).scalars()],
        "audit_events": [{"at": a.created_at.isoformat(), "action": a.action, "actor": a.actor_label, "hash": a.hash}
                         for a in db.execute(select(AuditEvent).where(AuditEvent.tenant_id == ctx.tenant.id)
                                             .order_by(AuditEvent.created_at)).scalars()],
        "note": "Connector secrets are never exported.",
    }
    audit.record(db, tenant_id=ctx.tenant.id, action="organization.exported", actor_id=ctx.user.id, actor_label=ctx.user.email)
    return Response(json.dumps(payload, indent=2), media_type="application/json",
                    headers={"content-disposition": f'attachment; filename="{ctx.tenant.slug}-export.json"'})


@router.post("/organizations/current/deletion", summary="Request organization deletion (30-day grace period)")
def request_deletion(ctx: Ctx = Depends(require("billing:manage"))) -> dict[str, object]:
    ctx.tenant.deletion_requested_at = utcnow()
    ctx.tenant.kill_switch = True
    audit.record(ctx.db, tenant_id=ctx.tenant.id, action="organization.deletion_requested", actor_id=ctx.user.id, actor_label=ctx.user.email)
    return {"deletion_scheduled_for": (utcnow() + timedelta(days=30)).isoformat(), "kill_switch": True}
