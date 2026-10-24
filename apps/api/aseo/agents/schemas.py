"""Typed agent contracts (Pydantic-validated inputs/outputs)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class IssueCluster(BaseModel):
    title: str = Field(max_length=200)
    explanation: str = Field(max_length=1200, description="Plain-language explanation grounded in the cited evidence")
    finding_ids: list[str]
    evidence_ids: list[str] = Field(description="IDs like finding:<uuid> or occurrence:<uuid> that support the explanation")
    priority: Literal["now", "next", "later"]
    deterministic: bool = Field(description="True if the cluster is made of deterministic defects, false for heuristic opportunities")


class AuditReport(BaseModel):
    summary: str = Field(max_length=1500)
    clusters: list[IssueCluster]
    limitations: list[str]


class PlanItemOut(BaseModel):
    finding_id: str | None
    action_type: str
    title: str = Field(max_length=200)
    rationale: str = Field(max_length=800)
    priority: int = Field(ge=1, le=100)
    impact: Literal["high", "medium", "low"]
    effort: Literal["high", "medium", "low"]
    evidence_ids: list[str]


class KeywordOpportunity(BaseModel):
    query: str
    page_url: str | None
    reason: str
    evidence_ids: list[str]
    source: Literal["gsc", "demo_fixture", "provider"]


class StrategyPlan(BaseModel):
    title: str
    summary: str = Field(max_length=1500)
    items: list[PlanItemOut]
    keyword_opportunities: list[KeywordOpportunity]
    caveats: list[str]


class MetadataDraft(BaseModel):
    value: str = Field(description="The proposed meta description or title text only")
    rationale: str = Field(max_length=600)
    evidence_ids: list[str]


class ContentBrief(BaseModel):
    title: str
    target_query: str
    search_intent: str
    outline: list[str]
    key_points: list[str]
    internal_link_suggestions: list[str]
    sources_needed: list[str]
    draft_markdown: str = Field(description="A first draft for an editor to review. It will never be published automatically.")
    caveats: list[str]


class ProposedAction(BaseModel):
    action_type: Literal["meta_description", "title"]
    url: str
    value: str
    rationale: str
    evidence_ids: list[str]


class CopilotAnswer(BaseModel):
    answer: str = Field(max_length=4000)
    citations: list[str] = Field(description="Evidence IDs that support the answer")
    proposed_actions: list[ProposedAction]
    limitations: list[str]


class MeasurementReport(BaseModel):
    technical_outcome: Literal["verified", "not_verified", "regressed", "unknown"]
    summary: str
    before: dict[str, float | int | None]
    after: dict[str, float | int | None]
    regression_warnings: list[str]
    caveats: list[str]
    evidence_ids: list[str]
