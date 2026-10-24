from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from aseo.models.base import Base, IdMixin, TenantMixin, TimestampMixin


class CrawlJob(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "crawl_jobs"
    __table_args__ = (Index("ix_crawl_jobs_site_status", "site_id", "status"),)
    site_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="queued")  # queued|running|completed|failed|cancelled
    trigger: Mapped[str] = mapped_column(String(20), default="manual")  # manual|schedule|event|onboarding|verification
    settings: Mapped[dict[str, Any]] = mapped_column(default=dict)
    stats: Mapped[dict[str, Any]] = mapped_column(default=dict)
    pages_crawled: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    dedupe_key: Mapped[str | None] = mapped_column(String(120))
    robots_txt: Mapped[str | None] = mapped_column(Text)
    sitemaps: Mapped[list[Any]] = mapped_column(default=list)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    requested_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class Page(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "pages"
    __table_args__ = (UniqueConstraint("site_id", "url_hash"), Index("ix_pages_site_status", "site_id", "status_code"))
    site_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"), index=True)
    url: Mapped[str] = mapped_column(Text)
    url_hash: Mapped[str] = mapped_column(String(64))
    path: Mapped[str] = mapped_column(Text)
    status_code: Mapped[int | None] = mapped_column(Integer)
    content_type: Mapped[str | None] = mapped_column(String(120))
    title: Mapped[str | None] = mapped_column(Text)
    meta_description: Mapped[str | None] = mapped_column(Text)
    h1: Mapped[str | None] = mapped_column(Text)
    canonical: Mapped[str | None] = mapped_column(Text)
    robots_meta: Mapped[str | None] = mapped_column(String(200))
    indexable: Mapped[bool | None] = mapped_column(Boolean)
    in_sitemap: Mapped[bool] = mapped_column(Boolean, default=False)
    depth: Mapped[int | None] = mapped_column(Integer)
    word_count: Mapped[int | None] = mapped_column(Integer)
    inlinks: Mapped[int] = mapped_column(Integer, default=0)
    outlinks: Mapped[int] = mapped_column(Integer, default=0)
    response_ms: Mapped[int | None] = mapped_column(Integer)
    redirect_target: Mapped[str | None] = mapped_column(Text)
    content_hash: Mapped[str | None] = mapped_column(String(64))
    last_crawl_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("crawl_jobs.id", ondelete="SET NULL"))
    last_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("page_snapshots.id", ondelete="SET NULL", use_alter=True), nullable=True
    )
    first_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Optional connector-specific resource reference, e.g. {"type": "post", "id": 12}
    resource_ref: Mapped[dict[str, Any] | None] = mapped_column()


class PageSnapshot(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "page_snapshots"
    page_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("pages.id", ondelete="CASCADE"), index=True)
    crawl_job_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("crawl_jobs.id", ondelete="CASCADE"), index=True)
    status_code: Mapped[int | None] = mapped_column(Integer)
    final_url: Mapped[str | None] = mapped_column(Text)
    redirect_chain: Mapped[list[Any]] = mapped_column(default=list)
    headers: Mapped[dict[str, Any]] = mapped_column(default=dict)
    content_hash: Mapped[str | None] = mapped_column(String(64))
    changed: Mapped[bool] = mapped_column(Boolean, default=True)
    storage_key: Mapped[str | None] = mapped_column(String(300))
    extracted: Mapped[dict[str, Any]] = mapped_column(default=dict)
    byte_size: Mapped[int | None] = mapped_column(Integer)
    response_ms: Mapped[int | None] = mapped_column(Integer)
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    purpose: Mapped[str] = mapped_column(String(20), default="crawl")  # crawl|verification


class CrawlEdge(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "crawl_edges"
    crawl_job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("crawl_jobs.id", ondelete="CASCADE"), index=True)
    source_page_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("pages.id", ondelete="CASCADE"), index=True)
    target_url: Mapped[str] = mapped_column(Text)
    target_page_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("pages.id", ondelete="SET NULL"))
    anchor_text: Mapped[str | None] = mapped_column(Text)
    nofollow: Mapped[bool] = mapped_column(Boolean, default=False)
    is_internal: Mapped[bool] = mapped_column(Boolean, default=True)
