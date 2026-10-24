"""Change sets, immutable patch versions, approvals, executions and rollback snapshots."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from aseo.models.base import Base, IdMixin, TenantMixin, TimestampMixin


class ChangeSet(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "change_sets"
    __table_args__ = (Index("ix_change_sets_site_status", "site_id", "status"),)
    site_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"), index=True)
    connector_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("connectors.id", ondelete="SET NULL"))
    finding_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("seo_findings.id", ondelete="SET NULL"))
    page_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("pages.id", ondelete="SET NULL"))
    action_type: Mapped[str] = mapped_column(String(60))
    title: Mapped[str] = mapped_column(String(300))
    resource_ref: Mapped[dict[str, Any]] = mapped_column(default=dict)
    status: Mapped[str] = mapped_column(String(30), default="draft")
    risk_score: Mapped[float | None] = mapped_column(Float)
    risk_level: Mapped[str | None] = mapped_column(String(20))
    policy_decision: Mapped[dict[str, Any] | None] = mapped_column()
    current_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("patch_versions.id", ondelete="SET NULL", use_alter=True)
    )
    source: Mapped[str] = mapped_column(String(20), default="deterministic")  # ai|deterministic|user
    agent_run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agent_runs.id", ondelete="SET NULL"))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    lock_version: Mapped[int] = mapped_column(Integer, default=1)
    is_fixture: Mapped[bool] = mapped_column(Boolean, default=False)

    __mapper_args__ = {"version_id_col": lock_version}


class PatchVersion(IdMixin, TimestampMixin, TenantMixin, Base):
    """Immutable once inserted (enforced by a database trigger)."""

    __tablename__ = "patch_versions"
    __table_args__ = (UniqueConstraint("change_set_id", "version"),)
    change_set_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("change_sets.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    patch: Mapped[dict[str, Any]] = mapped_column()
    before: Mapped[dict[str, Any]] = mapped_column(default=dict)
    resource_version: Mapped[str | None] = mapped_column(String(120))
    patch_hash: Mapped[str] = mapped_column(String(64), index=True)
    validation: Mapped[dict[str, Any]] = mapped_column(default=dict)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    rationale: Mapped[str | None] = mapped_column(Text)
    evidence_ids: Mapped[list[Any]] = mapped_column(default=list)


class Approval(IdMixin, TimestampMixin, TenantMixin, Base):
    """Append-only. Binds to the exact patch hash; invalidated if the change set gets a new version."""

    __tablename__ = "approvals"
    change_set_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("change_sets.id", ondelete="CASCADE"), index=True)
    patch_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patch_versions.id", ondelete="CASCADE"))
    patch_hash: Mapped[str] = mapped_column(String(64))
    site_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"))
    decision: Mapped[str] = mapped_column(String(20))  # approved|rejected|auto_approved
    reason: Mapped[str | None] = mapped_column(Text)
    decided_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    policy_snapshot: Mapped[dict[str, Any]] = mapped_column(default=dict)


class ExecutionRun(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "execution_runs"
    __table_args__ = (UniqueConstraint("tenant_id", "idempotency_key"), Index("ix_execution_runs_status", "status"))
    change_set_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("change_sets.id", ondelete="CASCADE"), index=True)
    patch_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patch_versions.id", ondelete="CASCADE"))
    patch_hash: Mapped[str] = mapped_column(String(64))
    approval_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("approvals.id", ondelete="SET NULL"))
    kind: Mapped[str] = mapped_column(String(20), default="apply")  # apply|rollback
    status: Mapped[str] = mapped_column(String(20), default="queued")
    # queued|running|verifying|succeeded|failed|cancelled|dead_letter|awaiting_deploy
    attempt: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    idempotency_key: Mapped[str] = mapped_column(String(200))
    connector_provider: Mapped[str | None] = mapped_column(String(30))
    connector_mode: Mapped[str | None] = mapped_column(String(20))
    connector_result: Mapped[dict[str, Any]] = mapped_column(default=dict)
    verification: Mapped[dict[str, Any]] = mapped_column(default=dict)
    error: Mapped[str | None] = mapped_column(Text)
    requested_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RollbackSnapshot(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "rollback_snapshots"
    execution_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("execution_runs.id", ondelete="CASCADE"), index=True)
    change_set_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("change_sets.id", ondelete="CASCADE"), index=True)
    resource_ref: Mapped[dict[str, Any]] = mapped_column(default=dict)
    previous_value: Mapped[dict[str, Any]] = mapped_column(default=dict)
    resource_version: Mapped[str | None] = mapped_column(String(120))
    restorable: Mapped[bool] = mapped_column(Boolean, default=True)
    restore_notes: Mapped[str | None] = mapped_column(Text)
    restored_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
