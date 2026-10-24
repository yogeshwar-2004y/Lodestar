"""Registration, organizations, workspaces, sessions."""

from __future__ import annotations

import re
import secrets
import uuid
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from aseo.core.config import get_settings
from aseo.core.db import set_session_tenant
from aseo.core.errors import Conflict, NotFound, Unauthorized
from aseo.core.security import hash_password, new_token, sha256_hex, verify_password
from aseo.models import ClientWorkspace, Membership, Tenant, User, UserSession, WorkspaceMembership
from aseo.models.base import utcnow
from aseo.services import audit, billing


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")[:60]
    return slug or "org"


def _unique_tenant_slug(db: Session, base: str) -> str:
    slug = slugify(base)
    candidate = slug
    while db.execute(select(func.count()).select_from(Tenant).where(Tenant.slug == candidate)).scalar_one():
        candidate = f"{slug}-{secrets.token_hex(2)}"
    return candidate


def create_user(db: Session, *, email: str, name: str, password: str) -> User:
    email = email.strip().lower()
    if db.execute(select(User).where(User.email == email)).scalar_one_or_none():
        raise Conflict("An account with this email already exists.", code="email_taken")
    user = User(email=email, name=name.strip(), password_hash=hash_password(password))
    db.add(user)
    db.flush()
    return user


def create_organization(
    db: Session, *, owner: User, name: str, kind: str = "business", locale: str = "en-US", timezone: str = "UTC",
    plan_key: str | None = None, is_demo: bool = False,
) -> tuple[Tenant, ClientWorkspace]:
    tenant = Tenant(name=name.strip(), slug=_unique_tenant_slug(db, name), kind=kind, locale=locale, timezone=timezone, is_demo=is_demo)
    db.add(tenant)
    db.flush()
    set_session_tenant(db, tenant.id)
    db.add(Membership(tenant_id=tenant.id, user_id=owner.id, role="owner"))
    ws = ClientWorkspace(tenant_id=tenant.id, name="Default" if kind != "agency" else "Agency (internal)", slug="default", is_default=True)
    db.add(ws)
    db.flush()
    db.add(WorkspaceMembership(tenant_id=tenant.id, workspace_id=ws.id, user_id=owner.id, role="owner"))
    billing.start_subscription(db, tenant.id, plan_key or ("agency" if kind == "agency" else "starter"))
    audit.record(db, tenant_id=tenant.id, action="organization.created", actor_id=owner.id, actor_label=owner.email,
                 target_type="tenant", target_id=tenant.id, data={"name": tenant.name, "kind": kind})
    return tenant, ws


def authenticate(db: Session, email: str, password: str) -> User:
    user = db.execute(select(User).where(User.email == email.strip().lower())).scalar_one_or_none()
    if user is None or not user.is_active or not verify_password(password, user.password_hash):
        # constant-ish work to reduce user enumeration timing differences
        if user is None:
            verify_password(password, "$argon2id$v=19$m=65536,t=3,p=4$c29tZXNhbHQ$RdescudvJCsgt3ub+b+dWRWJTmaaJObG")
        raise Unauthorized("Invalid email or password.", code="invalid_credentials")
    return user


def first_tenant_for(db: Session, user_id: uuid.UUID) -> uuid.UUID | None:
    return db.execute(
        select(Membership.tenant_id).where(Membership.user_id == user_id).order_by(Membership.created_at).limit(1)
    ).scalar_one_or_none()


def start_session(db: Session, user: User, *, ip: str | None, user_agent: str | None) -> tuple[str, UserSession]:
    token = new_token()
    sess = UserSession(
        user_id=user.id,
        token_hash=sha256_hex(token),
        csrf_token=new_token(24),
        active_tenant_id=first_tenant_for(db, user.id),
        expires_at=utcnow() + timedelta(hours=get_settings().session_ttl_hours),
        ip=ip,
        user_agent=(user_agent or "")[:300],
    )
    user.last_login_at = utcnow()
    db.add(sess)
    db.flush()
    return token, sess


def resolve_session(db: Session, token: str) -> UserSession:
    sess = db.execute(select(UserSession).where(UserSession.token_hash == sha256_hex(token))).scalar_one_or_none()
    if sess is None or sess.revoked_at is not None or sess.expires_at < utcnow():
        raise Unauthorized("Session expired. Please sign in again.", code="session_expired")
    return sess


def switch_tenant(db: Session, sess: UserSession, tenant_id: uuid.UUID) -> None:
    m = db.execute(select(Membership).where(Membership.user_id == sess.user_id, Membership.tenant_id == tenant_id)).scalar_one_or_none()
    if m is None:
        raise NotFound("Organization not found.")
    sess.active_tenant_id = tenant_id
