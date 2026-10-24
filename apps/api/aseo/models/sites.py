from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from aseo.models.base import Base, IdMixin, TenantMixin, TimestampMixin


class Site(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "sites"
    __table_args__ = (UniqueConstraint("tenant_id", "domain"),)
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("client_workspaces.id", ondelete="SET NULL"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    domain: Mapped[str] = mapped_column(String(255))  # normalized host[:port]
    base_url: Mapped[str] = mapped_column(String(500))
    platform: Mapped[str] = mapped_column(String(20), default="public")  # wordpress|shopify|github|public
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending|active|paused|error
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verification_method: Mapped[str | None] = mapped_column(String(30))
    crawl_settings: Mapped[dict[str, Any]] = mapped_column(default=dict)
    health_score: Mapped[float | None] = mapped_column(Float)
    health_breakdown: Mapped[dict[str, Any]] = mapped_column(default=dict)
    last_crawl_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    business_goals: Mapped[str | None] = mapped_column(Text)
    locale: Mapped[str] = mapped_column(String(20), default="en-US")
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    resource_lock_version: Mapped[int] = mapped_column(Integer, default=0)


class SiteVerification(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "site_verifications"
    site_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"), index=True)
    method: Mapped[str] = mapped_column(String(30))  # meta_tag|dns_txt|well_known_file|connector
    token: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending|verified|failed
    checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    evidence: Mapped[dict[str, Any]] = mapped_column(default=dict)


class Connector(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "connectors"
    __table_args__ = (UniqueConstraint("site_id", "provider"),)
    site_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(30))  # wordpress|shopify|github|gsc|public
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending|connected|disconnected|error
    # live = real credentials against a real site; fixture = labelled local test fixture.
    mode: Mapped[str] = mapped_column(String(20), default="live")
    config: Mapped[dict[str, Any]] = mapped_column(default=dict)  # non-secret settings only
    scopes: Mapped[list[Any]] = mapped_column(default=list)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)


class ConnectorCapability(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "connector_capabilities"
    __table_args__ = (UniqueConstraint("connector_id", "action_type"),)
    connector_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("connectors.id", ondelete="CASCADE"), index=True)
    action_type: Mapped[str] = mapped_column(String(60))
    supported: Mapped[bool] = mapped_column(Boolean, default=False)
    write_mode: Mapped[str] = mapped_column(String(20), default="none")  # direct|pull_request|none
    rollback_supported: Mapped[bool] = mapped_column(Boolean, default=False)
    preconditions: Mapped[list[Any]] = mapped_column(default=list)
    permissions: Mapped[list[Any]] = mapped_column(default=list)
    notes: Mapped[str | None] = mapped_column(Text)


class ConnectorSecretRef(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "connector_secret_refs"
    __table_args__ = (UniqueConstraint("connector_id", "name"),)
    connector_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("connectors.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(60))  # e.g. app_password, access_token
    backend: Mapped[str] = mapped_column(String(20))  # local|aws
    ref: Mapped[str] = mapped_column(String(300))  # opaque pointer into the backend
    fingerprint: Mapped[str] = mapped_column(String(16))  # non-reversible display hint
    rotated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SecretBlob(IdMixin, TimestampMixin, TenantMixin, Base):
    """Ciphertext storage for the local secret backend."""

    __tablename__ = "secret_blobs"
    ciphertext: Mapped[str] = mapped_column(Text)
