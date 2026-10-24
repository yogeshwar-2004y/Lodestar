from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from aseo.models.base import Base, IdMixin, TenantMixin, TimestampMixin


class Tenant(IdMixin, TimestampMixin, Base):
    """An organization (business or agency). Not RLS-protected because membership
    lookup must happen before a tenant is bound; access is checked in the service layer."""

    __tablename__ = "tenants"
    name: Mapped[str] = mapped_column(String(200))
    slug: Mapped[str] = mapped_column(String(80), unique=True)
    kind: Mapped[str] = mapped_column(String(20), default="business")  # business | saas | agency
    locale: Mapped[str] = mapped_column(String(20), default="en-US")
    timezone: Mapped[str] = mapped_column(String(60), default="UTC")
    kill_switch: Mapped[bool] = mapped_column(Boolean, default=False)
    branding: Mapped[dict[str, Any]] = mapped_column(default=dict)
    data_retention_days: Mapped[int] = mapped_column(Integer, default=365)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    deletion_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class User(IdMixin, TimestampMixin, Base):
    __tablename__ = "users"
    email: Mapped[str] = mapped_column(String(320), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    password_hash: Mapped[str] = mapped_column(String(255))
    locale: Mapped[str] = mapped_column(String(20), default="en-US")
    timezone: Mapped[str] = mapped_column(String(60), default="UTC")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Role(IdMixin, TimestampMixin, Base):
    """Role templates. tenant_id NULL = built-in template."""

    __tablename__ = "roles"
    __table_args__ = (UniqueConstraint("tenant_id", "key"),)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    key: Mapped[str] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(String(80))
    permissions: Mapped[list[Any]] = mapped_column(default=list)
    rank: Mapped[int] = mapped_column(Integer, default=0)


class Membership(IdMixin, TimestampMixin, Base):
    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("tenant_id", "user_id"),)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(40))  # owner|admin|editor|analyst|viewer|client


class UserSession(IdMixin, TimestampMixin, Base):
    __tablename__ = "user_sessions"
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    csrf_token: Mapped[str] = mapped_column(String(64))
    active_tenant_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tenants.id", ondelete="SET NULL"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ip: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(300))


class ClientWorkspace(IdMixin, TimestampMixin, TenantMixin, Base):
    """Agency client workspace (or the default workspace for a business)."""

    __tablename__ = "client_workspaces"
    __table_args__ = (UniqueConstraint("tenant_id", "slug"),)
    name: Mapped[str] = mapped_column(String(200))
    slug: Mapped[str] = mapped_column(String(80))
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    branding: Mapped[dict[str, Any]] = mapped_column(default=dict)
    notes: Mapped[str | None] = mapped_column(Text)


class WorkspaceMembership(IdMixin, TimestampMixin, TenantMixin, Base):
    """Per-workspace role. Users with an org role of owner/admin see all workspaces;
    everyone else (including 'client' users) only sees workspaces listed here."""

    __tablename__ = "workspace_memberships"
    __table_args__ = (UniqueConstraint("workspace_id", "user_id"),)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("client_workspaces.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(40))


class IdempotencyRecord(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "idempotency_keys"
    __table_args__ = (UniqueConstraint("tenant_id", "key"),)
    key: Mapped[str] = mapped_column(String(200))
    method: Mapped[str] = mapped_column(String(10))
    path: Mapped[str] = mapped_column(String(300))
    request_hash: Mapped[str] = mapped_column(String(64))
    response_status: Mapped[int | None] = mapped_column(Integer)
    response_body: Mapped[dict[str, Any] | None] = mapped_column()


class OAuthState(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "oauth_states"
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    provider: Mapped[str] = mapped_column(String(40))
    state_hash: Mapped[str] = mapped_column(String(64), unique=True)
    code_verifier_enc: Mapped[str | None] = mapped_column(Text)
    site_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"))
    extra: Mapped[dict[str, Any]] = mapped_column(default=dict)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
