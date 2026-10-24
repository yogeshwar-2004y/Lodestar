from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import Boolean, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from aseo.models.base import Base, IdMixin, TenantMixin, TimestampMixin


class SeoRule(IdMixin, TimestampMixin, Base):
    """Global rule catalogue (synced from code on startup/seed)."""

    __tablename__ = "seo_rules"
    key: Mapped[str] = mapped_column(String(80), unique=True)
    category: Mapped[str] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(String(20))  # critical|high|medium|low|info
    kind: Mapped[str] = mapped_column(String(20))  # deterministic|heuristic
    weight: Mapped[float] = mapped_column(Float, default=1.0)
    remediation: Mapped[str] = mapped_column(Text)
    fix_action: Mapped[str | None] = mapped_column(String(60))
    version: Mapped[int] = mapped_column(Integer, default=1)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class SeoFinding(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "seo_findings"
    __table_args__ = (
        UniqueConstraint("site_id", "fingerprint"),
        Index("ix_seo_findings_site_status_sev", "site_id", "status", "severity"),
    )
    site_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"), index=True)
    rule_key: Mapped[str] = mapped_column(String(80), index=True)
    fingerprint: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20), default="open")  # open|resolved|ignored|fix_pending
    severity: Mapped[str] = mapped_column(String(20))
    kind: Mapped[str] = mapped_column(String(20))
    category: Mapped[str] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(300))
    summary: Mapped[str] = mapped_column(Text)
    remediation: Mapped[str] = mapped_column(Text)
    fix_action: Mapped[str | None] = mapped_column(String(60))
    affected_count: Mapped[int] = mapped_column(Integer, default=0)
    evidence: Mapped[dict[str, Any]] = mapped_column(default=dict)
    first_seen_crawl_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("crawl_jobs.id", ondelete="SET NULL"))
    last_seen_crawl_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("crawl_jobs.id", ondelete="SET NULL"))
    ai_explanation: Mapped[dict[str, Any] | None] = mapped_column()


class FindingOccurrence(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "finding_occurrences"
    __table_args__ = (UniqueConstraint("finding_id", "page_id"),)
    finding_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("seo_findings.id", ondelete="CASCADE"), index=True)
    page_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("pages.id", ondelete="CASCADE"), index=True)
    snapshot_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("page_snapshots.id", ondelete="SET NULL"))
    crawl_job_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("crawl_jobs.id", ondelete="CASCADE"))
    url: Mapped[str] = mapped_column(Text)
    evidence: Mapped[dict[str, Any]] = mapped_column(default=dict)
    status: Mapped[str] = mapped_column(String(20), default="open")
