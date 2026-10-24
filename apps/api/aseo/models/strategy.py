"""Keywords, plans and content drafts."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from aseo.models.base import Base, IdMixin, TenantMixin, TimestampMixin


class KeywordCluster(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "keyword_clusters"
    site_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    intent: Mapped[str | None] = mapped_column(String(30))
    queries_count: Mapped[int] = mapped_column(Integer, default=0)
    clicks: Mapped[int] = mapped_column(Integer, default=0)
    impressions: Mapped[int] = mapped_column(Integer, default=0)
    opportunity_score: Mapped[float | None] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(30))  # gsc|provider:<name>|demo_fixture
    notes: Mapped[str | None] = mapped_column(Text)


class KeywordQuery(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "keyword_queries"
    site_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"), index=True)
    cluster_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("keyword_clusters.id", ondelete="SET NULL"))
    query: Mapped[str] = mapped_column(Text)
    page_url: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(30))
    clicks: Mapped[int] = mapped_column(Integer, default=0)
    impressions: Mapped[int] = mapped_column(Integer, default=0)
    ctr: Mapped[float | None] = mapped_column(Float)
    position: Mapped[float | None] = mapped_column(Float)
    # Only populated from a paid provider with explicit provenance — never estimated.
    search_volume: Mapped[int | None] = mapped_column(Integer)
    period_start: Mapped[date | None] = mapped_column(Date)
    period_end: Mapped[date | None] = mapped_column(Date)


class DataSourceSync(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "data_source_syncs"
    site_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"), index=True)
    source: Mapped[str] = mapped_column(String(30))  # gsc|psi|ga4|keyword_provider
    status: Mapped[str] = mapped_column(String(20), default="queued")
    rows: Mapped[int] = mapped_column(Integer, default=0)
    data_through: Mapped[date | None] = mapped_column(Date)
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_fixture: Mapped[bool] = mapped_column(Boolean, default=False)


class ActionPlan(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "action_plans"
    site_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(300))
    summary: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="active")
    goals: Mapped[dict[str, Any]] = mapped_column(default=dict)
    agent_run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agent_runs.id", ondelete="SET NULL"))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class PlanItem(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "plan_items"
    plan_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("action_plans.id", ondelete="CASCADE"), index=True)
    finding_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("seo_findings.id", ondelete="SET NULL"))
    action_type: Mapped[str] = mapped_column(String(60))
    title: Mapped[str] = mapped_column(String(300))
    rationale: Mapped[str] = mapped_column(Text)
    priority: Mapped[int] = mapped_column(Integer)
    impact: Mapped[str] = mapped_column(String(20))
    effort: Mapped[str] = mapped_column(String(20))
    evidence_ids: Mapped[list[Any]] = mapped_column(default=list)
    status: Mapped[str] = mapped_column(String(20), default="proposed")
    change_set_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("change_sets.id", ondelete="SET NULL"))


class ContentDraft(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "content_drafts"
    site_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(20))  # brief|article
    title: Mapped[str] = mapped_column(String(300))
    target_query: Mapped[str | None] = mapped_column(Text)
    brief: Mapped[dict[str, Any]] = mapped_column(default=dict)
    body: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft|in_review|approved|rejected
    review_notes: Mapped[str | None] = mapped_column(Text)
    editorial_approved_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    editorial_approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ai_generated: Mapped[bool] = mapped_column(Boolean, default=True)
    agent_run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agent_runs.id", ondelete="SET NULL"))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
