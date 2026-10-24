"""Shared API response contracts."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, EmailStr, Field

T = TypeVar("T")


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Page_(BaseModel, Generic[T]):
    items: list[T]
    next_cursor: str | None = None


class Accepted(BaseModel):
    id: uuid.UUID
    status: str
    status_url: str


# ------------------------------------------------------------------ auth / orgs


class RegisterIn(BaseModel):
    email: EmailStr
    name: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=10, max_length=200)
    organization_name: str | None = Field(default=None, max_length=200)
    organization_kind: Literal["business", "saas", "agency"] = "business"

    model_config = ConfigDict(json_schema_extra={"example": {"email": "owner@example.com", "name": "Ada Owner",
                                                             "password": "correct horse battery", "organization_name": "Northwind"}})


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)


class UserOut(ORM):
    id: uuid.UUID
    email: str
    name: str
    locale: str
    timezone: str


class OrgOut(ORM):
    id: uuid.UUID
    name: str
    slug: str
    kind: str
    locale: str
    timezone: str
    kill_switch: bool
    branding: dict[str, Any]
    data_retention_days: int
    is_demo: bool


class MembershipOut(BaseModel):
    organization: OrgOut
    role: str


class SessionOut(BaseModel):
    user: UserOut
    organization: OrgOut | None
    role: str | None
    permissions: list[str]
    memberships: list[MembershipOut]
    csrf_token: str
    token: str | None = Field(default=None, description="Returned only on login/register for non-browser API clients")


class OrgCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    kind: Literal["business", "saas", "agency"] = "business"
    locale: str = "en-US"
    timezone: str = "UTC"


class OrgUpdateIn(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    locale: str | None = None
    timezone: str | None = None
    branding: dict[str, Any] | None = None
    data_retention_days: int | None = Field(default=None, ge=30, le=3650)


class WorkspaceIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    branding: dict[str, Any] = Field(default_factory=dict)
    notes: str | None = None


class WorkspaceOut(ORM):
    id: uuid.UUID
    name: str
    slug: str
    is_default: bool
    branding: dict[str, Any]
    created_at: datetime


class MemberIn(BaseModel):
    email: EmailStr
    name: str = Field(min_length=1, max_length=200)
    role: Literal["admin", "editor", "analyst", "viewer", "client"]
    password: str | None = Field(default=None, min_length=10, description="Initial password if the user does not exist yet")
    workspace_ids: list[uuid.UUID] = Field(default_factory=list)


class MemberOut(BaseModel):
    user_id: uuid.UUID
    email: str
    name: str
    role: str
    workspaces: list[uuid.UUID]


# ------------------------------------------------------------------ sites


class SiteIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    url: str = Field(min_length=3, max_length=500)
    platform: Literal["wordpress", "shopify", "github", "public"] = "public"
    workspace_id: uuid.UUID | None = None
    business_goals: str | None = Field(default=None, max_length=2000)
    crawl_settings: dict[str, Any] | None = None

    model_config = ConfigDict(json_schema_extra={"example": {"name": "Northwind", "url": "https://northwind.example", "platform": "wordpress"}})


class SiteUpdateIn(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    business_goals: str | None = Field(default=None, max_length=2000)
    crawl_settings: dict[str, Any] | None = None
    workspace_id: uuid.UUID | None = None


class SiteOut(ORM):
    id: uuid.UUID
    workspace_id: uuid.UUID | None
    name: str
    domain: str
    base_url: str
    platform: str
    status: str
    verified_at: datetime | None
    verification_method: str | None
    crawl_settings: dict[str, Any]
    health_score: float | None
    health_breakdown: dict[str, Any]
    last_crawl_at: datetime | None
    business_goals: str | None
    is_demo: bool
    created_at: datetime


class VerificationStartIn(BaseModel):
    method: Literal["meta_tag", "dns_txt", "well_known_file", "connector"]


class VerificationOut(ORM):
    id: uuid.UUID
    method: str
    status: str
    checked_at: datetime | None
    verified_at: datetime | None
    evidence: dict[str, Any]


class ConnectorIn(BaseModel):
    provider: Literal["wordpress", "shopify", "github"]
    config: dict[str, Any] = Field(default_factory=dict, description="Non-secret settings, e.g. {'username': 'lodestar-agent'}")
    secrets: dict[str, str] = Field(default_factory=dict, description="Write-only. Stored encrypted by reference; never returned.")
    mode: Literal["live", "fixture"] = "live"


class CapabilityOut(ORM):
    action_type: str
    supported: bool
    write_mode: str
    rollback_supported: bool
    preconditions: list[Any]
    permissions: list[Any]
    notes: str | None


class ConnectorOut(BaseModel):
    id: uuid.UUID
    provider: str
    status: str
    mode: str
    config: dict[str, Any]
    scopes: list[Any]
    last_checked_at: datetime | None
    last_error: str | None
    capabilities: list[CapabilityOut]
    secrets: list[dict[str, Any]]


class CrawlIn(BaseModel):
    max_pages: int | None = Field(default=None, ge=1, le=10000)
    include_paths: list[str] | None = None
    exclude_paths: list[str] | None = None


class CrawlOut(ORM):
    id: uuid.UUID
    site_id: uuid.UUID
    status: str
    trigger: str
    settings: dict[str, Any]
    stats: dict[str, Any]
    pages_crawled: int
    error: str | None
    sitemaps: list[Any]
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime


class PageOut(ORM):
    id: uuid.UUID
    url: str
    path: str
    status_code: int | None
    title: str | None
    meta_description: str | None
    h1: str | None
    canonical: str | None
    robots_meta: str | None
    indexable: bool | None
    in_sitemap: bool
    depth: int | None
    word_count: int | None
    inlinks: int
    outlinks: int
    response_ms: int | None
    redirect_target: str | None
    last_seen_at: datetime | None
    created_at: datetime


class FindingOut(ORM):
    id: uuid.UUID
    site_id: uuid.UUID
    rule_key: str
    status: str
    severity: str
    kind: str
    category: str
    title: str
    summary: str
    remediation: str
    fix_action: str | None
    affected_count: int
    evidence: dict[str, Any]
    ai_explanation: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime


class OccurrenceOut(ORM):
    id: uuid.UUID
    page_id: uuid.UUID | None
    snapshot_id: uuid.UUID | None
    url: str
    evidence: dict[str, Any]
    status: str


# ------------------------------------------------------------------ change sets


class ChangeSetIn(BaseModel):
    site_id: uuid.UUID
    url: str
    action_type: Literal["meta_description", "title"]
    value: str | None = Field(default=None, max_length=400, description="Leave empty to have the Execution Agent draft it")
    finding_id: uuid.UUID | None = None
    rationale: str | None = Field(default=None, max_length=1000)


class ValidateIn(BaseModel):
    value: str | None = Field(default=None, max_length=400, description="Optional revised value. Creates a NEW immutable version; "
                                                                        "previous approvals no longer apply.")
    rationale: str | None = None


class DecisionIn(BaseModel):
    patch_hash: str = Field(min_length=64, max_length=64, description="Hash of the exact version the reviewer saw")
    reason: str | None = Field(default=None, max_length=1000)


class RejectIn(DecisionIn):
    reason: str = Field(min_length=3, max_length=1000)


class ExecuteIn(BaseModel):
    patch_hash: str = Field(min_length=64, max_length=64)

    model_config = ConfigDict(extra="forbid")  # execute never accepts patch content


class RollbackIn(BaseModel):
    reason: str | None = Field(default=None, max_length=1000)


class PatchVersionOut(ORM):
    id: uuid.UUID
    version: int
    patch: dict[str, Any]
    before: dict[str, Any]
    resource_version: str | None
    patch_hash: str
    validation: dict[str, Any]
    rationale: str | None
    evidence_ids: list[Any]
    created_at: datetime


class ApprovalOut(ORM):
    id: uuid.UUID
    patch_version_id: uuid.UUID
    patch_hash: str
    decision: str
    reason: str | None
    decided_by: uuid.UUID | None
    created_at: datetime


class ExecutionOut(ORM):
    id: uuid.UUID
    change_set_id: uuid.UUID
    patch_hash: str
    kind: str
    status: str
    attempt: int
    connector_provider: str | None
    connector_mode: str | None
    connector_result: dict[str, Any]
    verification: dict[str, Any]
    error: str | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime


class ChangeSetOut(ORM):
    id: uuid.UUID
    site_id: uuid.UUID
    finding_id: uuid.UUID | None
    page_id: uuid.UUID | None
    action_type: str
    title: str
    resource_ref: dict[str, Any]
    status: str
    risk_score: float | None
    risk_level: str | None
    policy_decision: dict[str, Any] | None
    source: str
    is_fixture: bool
    created_at: datetime
    updated_at: datetime


class ChangeSetDetail(ChangeSetOut):
    current_version: PatchVersionOut | None
    versions: list[PatchVersionOut]
    approvals: list[ApprovalOut]
    executions: list[ExecutionOut]
    connector: dict[str, Any] | None
    rollback_available: bool
    rollback_note: str | None


# ------------------------------------------------------------------ misc


class AutomationPolicyIn(BaseModel):
    mode: Literal["observe", "assist", "autopilot"]
    auto_actions: list[Literal["meta_description", "title"]] = Field(default_factory=list)
    path_scope: list[str] = Field(default_factory=list)
    max_auto_changes_per_day: int = Field(default=10, ge=0, le=500)
    max_risk_score: float = Field(default=0.3, ge=0, le=1)
    paused: bool = False


class ScheduleIn(BaseModel):
    kind: Literal["crawl"] = "crawl"
    interval_minutes: int = Field(ge=60, le=60 * 24 * 31)
    enabled: bool = True


class CopilotIn(BaseModel):
    site_id: uuid.UUID
    message: str = Field(min_length=2, max_length=2000)


class ReportIn(BaseModel):
    site_id: uuid.UUID
    title: str | None = Field(default=None, max_length=300)
    period_days: int = Field(default=28, ge=7, le=365)


class ContentDraftIn(BaseModel):
    target_query: str = Field(min_length=2, max_length=200)
    notes: str | None = Field(default=None, max_length=2000)


class ContentReviewIn(BaseModel):
    notes: str | None = Field(default=None, max_length=2000)
    body: str | None = Field(default=None, max_length=100_000)


class AnnotationOut(ORM):
    id: uuid.UUID
    date: date
    kind: str
    title: str
    change_set_id: uuid.UUID | None
