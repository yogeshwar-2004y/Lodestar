"""Automation, workflows, agents, analytics, billing, audit and notifications."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from aseo.models.base import Base, IdMixin, TenantMixin, TimestampMixin

# ---------------------------------------------------------------- automation


class AutomationPolicy(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "automation_policies"
    __table_args__ = (UniqueConstraint("site_id"),)
    site_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"))
    mode: Mapped[str] = mapped_column(String(20), default="assist")  # observe|assist|autopilot
    auto_actions: Mapped[list[Any]] = mapped_column(default=list)  # whitelisted action types for autopilot
    path_scope: Mapped[list[Any]] = mapped_column(default=list)  # path prefixes autopilot may touch
    max_auto_changes_per_day: Mapped[int] = mapped_column(Integer, default=10)
    max_risk_score: Mapped[float] = mapped_column(Float, default=0.3)
    paused: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class AutomationSchedule(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "automation_schedules"
    site_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(30))  # crawl|gsc_sync|measurement|report
    interval_minutes: Mapped[int] = mapped_column(Integer, default=1440)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EventInbox(IdMixin, TimestampMixin, Base):
    """Inbound webhooks. (provider, event_id) unique => replay protection."""

    __tablename__ = "event_inbox"
    __table_args__ = (UniqueConstraint("provider", "event_id"),)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(30))
    event_id: Mapped[str] = mapped_column(String(200))
    event_type: Mapped[str] = mapped_column(String(100))
    payload: Mapped[dict[str, Any]] = mapped_column(default=dict)
    status: Mapped[str] = mapped_column(String(20), default="received")
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)


class OutboxEvent(IdMixin, TimestampMixin, Base):
    """Transactional outbox: side-effecting jobs are written in the same transaction as the
    state change and dispatched afterwards by the outbox relay."""

    __tablename__ = "outbox_events"
    __table_args__ = (Index("ix_outbox_status_available", "status", "available_at"),)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    topic: Mapped[str] = mapped_column(String(60))
    payload: Mapped[dict[str, Any]] = mapped_column(default=dict)
    dedupe_key: Mapped[str | None] = mapped_column(String(200), unique=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending|processing|done|failed|dead
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=5)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WorkflowRun(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "workflow_runs"
    site_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(20), default="running")
    trigger: Mapped[str] = mapped_column(String(30), default="manual")
    current_step: Mapped[str | None] = mapped_column(String(60))
    steps: Mapped[list[Any]] = mapped_column(default=list)
    state: Mapped[dict[str, Any]] = mapped_column(default=dict)
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AgentRun(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "agent_runs"
    workflow_run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("workflow_runs.id", ondelete="CASCADE"), index=True)
    site_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"), index=True)
    agent: Mapped[str] = mapped_column(String(20))  # audit|strategy|execution|measurement|copilot
    task: Mapped[str] = mapped_column(String(60))
    status: Mapped[str] = mapped_column(String(20), default="running")
    input: Mapped[dict[str, Any]] = mapped_column(default=dict)
    output: Mapped[dict[str, Any] | None] = mapped_column()
    provider: Mapped[str] = mapped_column(String(30))
    model: Mapped[str] = mapped_column(String(60))
    prompt_version: Mapped[str] = mapped_column(String(30))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Numeric(12, 6), default=0)
    credits_charged: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    evidence_ids: Mapped[list[Any]] = mapped_column(default=list)
    error: Mapped[str | None] = mapped_column(Text)


class ToolInvocation(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "tool_invocations"
    agent_run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agent_runs.id", ondelete="CASCADE"), index=True)
    tool: Mapped[str] = mapped_column(String(60))
    args: Mapped[dict[str, Any]] = mapped_column(default=dict)
    result_summary: Mapped[dict[str, Any]] = mapped_column(default=dict)
    status: Mapped[str] = mapped_column(String(20), default="ok")
    duration_ms: Mapped[int | None] = mapped_column(Integer)


# ---------------------------------------------------------------- analytics


class SearchMetric(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "search_metrics"
    __table_args__ = (
        UniqueConstraint("site_id", "date", "page", "query", "source"),
        Index("ix_search_metrics_site_date", "site_id", "date"),
    )
    site_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"))
    date: Mapped[date] = mapped_column(Date)
    page: Mapped[str] = mapped_column(Text, default="")
    query: Mapped[str] = mapped_column(Text, default="")
    clicks: Mapped[int] = mapped_column(Integer, default=0)
    impressions: Mapped[int] = mapped_column(Integer, default=0)
    ctr: Mapped[float] = mapped_column(Float, default=0)
    position: Mapped[float | None] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(20))  # gsc|demo_fixture


class MeasurementAnnotation(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "measurement_annotations"
    site_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"), index=True)
    date: Mapped[date] = mapped_column(Date)
    kind: Mapped[str] = mapped_column(String(20))  # change|deployment|rollback|note
    title: Mapped[str] = mapped_column(String(300))
    change_set_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("change_sets.id", ondelete="SET NULL"))
    execution_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("execution_runs.id", ondelete="SET NULL"))


class Report(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "reports"
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("client_workspaces.id", ondelete="SET NULL"))
    site_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(300))
    kind: Mapped[str] = mapped_column(String(30), default="site_health")
    status: Mapped[str] = mapped_column(String(20), default="queued")
    period_start: Mapped[date | None] = mapped_column(Date)
    period_end: Mapped[date | None] = mapped_column(Date)
    branding: Mapped[dict[str, Any]] = mapped_column(default=dict)
    content: Mapped[dict[str, Any]] = mapped_column(default=dict)
    storage_key: Mapped[str | None] = mapped_column(String(300))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# ---------------------------------------------------------------- billing


class Plan(IdMixin, TimestampMixin, Base):
    """Editable plan catalogue. Amounts are seed data, not hardcoded in logic."""

    __tablename__ = "plans"
    key: Mapped[str] = mapped_column(String(40), unique=True)
    name: Mapped[str] = mapped_column(String(80))
    monthly_price_cents: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    included_credits: Mapped[int] = mapped_column(Integer)
    max_sites: Mapped[int] = mapped_column(Integer)
    max_pages_per_crawl: Mapped[int] = mapped_column(Integer)
    max_workspaces: Mapped[int] = mapped_column(Integer, default=1)
    features: Mapped[list[Any]] = mapped_column(default=list)
    provider_price_ref: Mapped[str | None] = mapped_column(String(120))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort: Mapped[int] = mapped_column(Integer, default=0)


class Subscription(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "subscriptions"
    __table_args__ = (UniqueConstraint("tenant_id"),)
    plan_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("plans.id"))
    status: Mapped[str] = mapped_column(String(20), default="trialing")
    provider: Mapped[str] = mapped_column(String(20), default="test")
    provider_ref: Mapped[str | None] = mapped_column(String(120))
    current_period_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    current_period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_at_period_end: Mapped[bool] = mapped_column(Boolean, default=False)


class CreditLedger(IdMixin, TimestampMixin, TenantMixin, Base):
    """Append-only (DB trigger). Each charge is unique per idempotency key."""

    __tablename__ = "credit_ledger"
    __table_args__ = (UniqueConstraint("tenant_id", "idempotency_key"),)
    seq: Mapped[int] = mapped_column(BigInteger, Identity(), unique=True)
    delta: Mapped[int] = mapped_column(Integer)
    balance_after: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(60))  # grant|ai_usage|crawl|refund|adjustment|reservation
    ref_type: Mapped[str | None] = mapped_column(String(40))
    ref_id: Mapped[str | None] = mapped_column(String(80))
    idempotency_key: Mapped[str] = mapped_column(String(200))
    meta: Mapped[dict[str, Any]] = mapped_column(default=dict)


class UsageRecord(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "usage_records"
    __table_args__ = (Index("ix_usage_tenant_metric_period", "tenant_id", "metric", "period"),)
    metric: Mapped[str] = mapped_column(String(40))  # pages_crawled|ai_input_tokens|ai_output_tokens|executions
    quantity: Mapped[int] = mapped_column(BigInteger)
    period: Mapped[str] = mapped_column(String(7))  # YYYY-MM
    ref_type: Mapped[str | None] = mapped_column(String(40))
    ref_id: Mapped[str | None] = mapped_column(String(80))


# ---------------------------------------------------------------- audit & notifications


class AuditEvent(IdMixin, TenantMixin, Base):
    """Append-only and hash-chained per tenant (tamper evident)."""

    __tablename__ = "audit_events"
    __table_args__ = (Index("ix_audit_tenant_created", "tenant_id", "created_at"),)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    actor_type: Mapped[str] = mapped_column(String(20))  # user|system|agent|webhook
    actor_id: Mapped[str | None] = mapped_column(String(80))
    actor_label: Mapped[str | None] = mapped_column(String(200))
    action: Mapped[str] = mapped_column(String(80))
    target_type: Mapped[str | None] = mapped_column(String(40))
    target_id: Mapped[str | None] = mapped_column(String(80))
    site_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("sites.id", ondelete="SET NULL"), index=True)
    data: Mapped[dict[str, Any]] = mapped_column(default=dict)
    request_id: Mapped[str | None] = mapped_column(String(64))
    ip: Mapped[str | None] = mapped_column(String(64))
    prev_hash: Mapped[str | None] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64))


class Notification(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "notifications"
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(40))
    severity: Mapped[str] = mapped_column(String(20), default="info")
    title: Mapped[str] = mapped_column(String(300))
    body: Mapped[str | None] = mapped_column(Text)
    link: Mapped[str | None] = mapped_column(String(300))
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
