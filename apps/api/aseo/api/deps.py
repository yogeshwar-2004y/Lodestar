"""Request context: authentication, CSRF, tenant binding, RBAC and workspace scoping.

Tenant identity always comes from the authenticated session — never from request bodies.
"""

from __future__ import annotations

import base64
import json
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from aseo.core.config import get_settings
from aseo.core.db import new_session, set_session_tenant
from aseo.core.errors import Conflict, Forbidden, NotFound, Unauthorized, ValidationFailed
from aseo.core.security import constant_time_eq, sha256_hex
from aseo.models import IdempotencyRecord, Membership, Site, Tenant, User, UserSession, WorkspaceMembership
from aseo.services import outbox, rbac
from aseo.services.changes import Actor
from aseo.services.tenancy import resolve_session

UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}


def get_db(request: Request) -> Iterator[Session]:
    db = new_session()
    request.state.db = db
    try:
        yield db
        db.commit()
        if db.info.get("outbox_enqueued"):
            outbox.kick()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def client_ip(request: Request) -> str:
    return (request.client.host if request.client else "unknown")[:64]


@dataclass
class Ctx:
    db: Session
    user: User
    session: UserSession
    tenant: Tenant
    role: str
    request: Request
    workspace_ids: set[uuid.UUID] | None  # None => all workspaces

    @property
    def actor(self) -> Actor:
        return Actor("user", self.user.id, self.user.email, client_ip(self.request))

    def can(self, permission: str, role: str | None = None) -> bool:
        return rbac.has_permission(role or self.role, permission)

    def require(self, permission: str) -> None:
        if not self.can(permission):
            raise Forbidden(f"Your role ({self.role}) cannot perform this action.", code="insufficient_role",
                            details={"permission": permission})

    def workspace_role(self, workspace_id: uuid.UUID | None) -> str:
        if self.workspace_ids is None or workspace_id is None:
            return self.role
        wm = self.db.execute(select(WorkspaceMembership).where(WorkspaceMembership.workspace_id == workspace_id,
                                                               WorkspaceMembership.user_id == self.user.id)).scalar_one_or_none()
        return wm.role if wm else self.role

    def site(self, site_id: uuid.UUID, permission: str = "site:read") -> Site:
        site = self.db.get(Site, site_id)
        # RLS already hides other tenants' rows; the explicit check is defence in depth.
        if site is None or site.tenant_id != self.tenant.id:
            raise NotFound("Site not found")
        if self.workspace_ids is not None and site.workspace_id not in self.workspace_ids:
            raise NotFound("Site not found")  # do not reveal existence across client boundaries
        role = self.workspace_role(site.workspace_id)
        if not rbac.has_permission(role, permission):
            raise Forbidden(f"Your role ({role}) cannot perform this action on this site.", code="insufficient_role",
                            details={"permission": permission})
        return site

    def site_filter(self) -> Any:
        if self.workspace_ids is None:
            return Site.tenant_id == self.tenant.id
        return (Site.tenant_id == self.tenant.id) & (Site.workspace_id.in_(self.workspace_ids))


def _token(request: Request) -> tuple[str | None, bool]:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip(), False
    return request.cookies.get(get_settings().session_cookie_name), True


def get_ctx(request: Request, db: Session = Depends(get_db)) -> Ctx:
    token, via_cookie = _token(request)
    if not token:
        raise Unauthorized("Sign in required.")
    sess = resolve_session(db, token)
    if via_cookie and request.method in UNSAFE:
        header = request.headers.get("x-csrf-token", "")
        if not header or not constant_time_eq(header, sess.csrf_token):
            raise Forbidden("Missing or invalid CSRF token.", code="csrf_failed")
    user = db.get(User, sess.user_id)
    if user is None or not user.is_active:
        raise Unauthorized("Account disabled.")
    if sess.active_tenant_id is None:
        raise Forbidden("Create or join an organization first.", code="no_organization")
    membership = db.execute(select(Membership).where(Membership.user_id == user.id,
                                                     Membership.tenant_id == sess.active_tenant_id)).scalar_one_or_none()
    if membership is None:
        raise Forbidden("You are no longer a member of this organization.", code="not_a_member")
    tenant = db.get(Tenant, membership.tenant_id)
    assert tenant is not None
    set_session_tenant(db, tenant.id)
    ws_ids: set[uuid.UUID] | None = None
    if not rbac.sees_all_workspaces(membership.role):
        ws_ids = set(db.execute(select(WorkspaceMembership.workspace_id).where(WorkspaceMembership.user_id == user.id)).scalars())
    request.state.tenant_id = str(tenant.id)
    return Ctx(db, user, sess, tenant, membership.role, request, ws_ids)


def get_user_session(request: Request, db: Session = Depends(get_db)) -> tuple[User, UserSession]:
    """Authenticated user without requiring an organization (used during onboarding)."""
    token, via_cookie = _token(request)
    if not token:
        raise Unauthorized("Sign in required.")
    sess = resolve_session(db, token)
    if via_cookie and request.method in UNSAFE:
        header = request.headers.get("x-csrf-token", "")
        if not header or not constant_time_eq(header, sess.csrf_token):
            raise Forbidden("Missing or invalid CSRF token.", code="csrf_failed")
    user = db.get(User, sess.user_id)
    if user is None:
        raise Unauthorized("Sign in required.")
    return user, sess


def require(permission: str) -> Callable[[Ctx], Ctx]:
    def dep(ctx: Ctx = Depends(get_ctx)) -> Ctx:
        ctx.require(permission)
        return ctx

    return dep


# ------------------------------------------------------------------ idempotency


def idempotent(ctx: Ctx, key: str | None, body: Any, fn: Callable[[], tuple[int, Any]]) -> tuple[int, Any]:
    """Replay-safe writes: the same Idempotency-Key + same body returns the stored response;
    a different body with a reused key is rejected."""
    if not key:
        return fn()
    if len(key) > 200:
        raise ValidationFailed("Idempotency-Key too long")
    req_hash = sha256_hex(json.dumps(body, sort_keys=True, default=str))
    path = ctx.request.url.path
    rec = ctx.db.execute(select(IdempotencyRecord).where(IdempotencyRecord.tenant_id == ctx.tenant.id,
                                                        IdempotencyRecord.key == key)).scalar_one_or_none()
    if rec is not None:
        if rec.request_hash != req_hash or rec.path != path:
            raise Conflict("Idempotency-Key was already used with a different request.", code="idempotency_key_reused")
        if rec.response_status is not None:
            return rec.response_status, rec.response_body
    status, payload = fn()
    rec = IdempotencyRecord(tenant_id=ctx.tenant.id, key=key, method=ctx.request.method, path=path, request_hash=req_hash,
                            response_status=status, response_body=json.loads(json.dumps(payload, default=str)))
    ctx.db.add(rec)
    ctx.db.flush()
    return status, payload


# ------------------------------------------------------------------ cursor pagination


def encode_cursor(created_at: datetime, row_id: uuid.UUID) -> str:
    return base64.urlsafe_b64encode(f"{created_at.isoformat()}|{row_id}".encode()).decode()


def decode_cursor(cursor: str | None) -> tuple[datetime, uuid.UUID] | None:
    if not cursor:
        return None
    try:
        raw = base64.urlsafe_b64decode(cursor.encode()).decode()
        ts, rid = raw.split("|")
        return datetime.fromisoformat(ts), uuid.UUID(rid)
    except Exception as exc:  # noqa: BLE001
        raise ValidationFailed("Invalid cursor") from exc


def paginate(db: Session, query: Any, model: Any, cursor: str | None, limit: int) -> tuple[list[Any], str | None]:
    limit = max(1, min(limit, 200))
    c = decode_cursor(cursor)
    if c:
        ts, rid = c
        query = query.where((model.created_at < ts) | ((model.created_at == ts) & (model.id < rid)))
    rows = list(db.execute(query.order_by(model.created_at.desc(), model.id.desc()).limit(limit + 1)).scalars())
    nxt = encode_cursor(rows[limit - 1].created_at, rows[limit - 1].id) if len(rows) > limit else None
    return rows[:limit], nxt
