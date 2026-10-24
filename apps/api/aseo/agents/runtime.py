"""Agent runtime: bounded, tenant-scoped tools; persisted AgentRun/ToolInvocation records;
budget checks before calls and exactly-once credit charging after."""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from aseo.ai.gateway import AIResult, Gateway
from aseo.core.errors import AppError
from aseo.models import (
    AgentRun,
    ChangeSet,
    ExecutionRun,
    FindingOccurrence,
    KeywordQuery,
    Page,
    PageSnapshot,
    SearchMetric,
    SeoFinding,
    Site,
    ToolInvocation,
)
from aseo.models.base import utcnow
from aseo.services import billing

# Bounded tool sets per agent (no browsing, shell, secrets or cross-tenant tools).
AGENT_TOOLS = {
    "audit": ["get_page_snapshot", "list_findings", "validate_schema", "inspect_sitemap"],
    "strategy": ["get_search_queries", "get_findings", "cluster_keywords", "propose_metadata", "draft_content"],
    "execution": ["prepare_patch", "validate_patch", "request_approval", "apply_authorized_patch", "verify_change", "rollback"],
    "measurement": ["get_gsc_metrics", "compare_periods", "get_execution_history", "schedule_crawl"],
    "copilot": ["list_findings", "get_page_snapshot", "get_search_queries", "get_execution_history"],
}
ESTIMATED_CREDITS_PER_CALL = 8


class Tools:
    """Tool implementations. Every query is scoped to ``site`` (and RLS scopes the tenant)."""

    def __init__(self, db: Session, site: Site, run: AgentRun) -> None:
        self.db, self.site, self.run = db, site, run

    def _record(self, tool: str, args: dict[str, Any], fn: Callable[[], Any]) -> Any:
        allowed = AGENT_TOOLS.get(self.run.agent, [])
        if tool not in allowed:
            raise PermissionError(f"tool {tool} not available to {self.run.agent} agent")
        t0 = time.monotonic()
        status = "ok"
        try:
            result = fn()
            return result
        except Exception:
            status = "error"
            raise
        finally:
            summary = {"count": len(result) if status == "ok" and isinstance(result, list) else None} if status == "ok" else {}
            self.db.add(ToolInvocation(tenant_id=self.site.tenant_id, agent_run_id=self.run.id, tool=tool, args=args,
                                       result_summary=summary, status=status, duration_ms=int((time.monotonic() - t0) * 1000)))

    def list_findings(self, limit: int = 40, status: str = "open", _tool: str = "list_findings") -> list[dict[str, Any]]:
        def go() -> list[dict[str, Any]]:
            rows = self.db.execute(select(SeoFinding).where(SeoFinding.site_id == self.site.id, SeoFinding.status == status)
                                   .order_by(SeoFinding.severity, SeoFinding.affected_count.desc()).limit(limit)).scalars()
            out = []
            for f in rows:
                occ = self.db.execute(select(FindingOccurrence).where(FindingOccurrence.finding_id == f.id).limit(5)).scalars().all()
                out.append({"evidence_id": f"finding:{f.id}", "id": str(f.id), "rule": f.rule_key, "kind": f.kind, "severity": f.severity,
                            "category": f.category, "title": f.title, "affected": f.affected_count, "fix_action": f.fix_action,
                            "examples": [{"evidence_id": f"occurrence:{o.id}", "url": o.url, "evidence": o.evidence} for o in occ]})
            return out

        return self._record(_tool, {"limit": limit, "status": status}, go)

    def get_findings(self, limit: int = 40, status: str = "open") -> list[dict[str, Any]]:
        return self.list_findings(limit, status, _tool="get_findings")

    def get_page_snapshot(self, url: str, _tool: str = "get_page_snapshot") -> dict[str, Any] | None:
        def go() -> dict[str, Any] | None:
            page = self.db.execute(select(Page).where(Page.site_id == self.site.id, Page.url == url)).scalar_one_or_none()
            if page is None or page.last_snapshot_id is None:
                return None
            snap = self.db.get(PageSnapshot, page.last_snapshot_id)
            ex = snap.extracted if snap else {}
            return {"evidence_id": f"snapshot:{snap.id}" if snap else None, "page_id": str(page.id), "url": page.url,
                    "status": page.status_code, "title": page.title, "meta_description": page.meta_description,
                    "h1": page.h1, "headings": (ex.get("headings") or [])[:15], "word_count": page.word_count,
                    "first_paragraph": ex.get("first_paragraph"), "text_excerpt": (ex.get("text_excerpt") or "")[:1200],
                    "indexable": page.indexable}

        return self._record(_tool, {"url": url}, go)

    def inspect_sitemap(self) -> dict[str, Any]:
        def go() -> dict[str, Any]:
            total = self.db.execute(select(Page).where(Page.site_id == self.site.id)).scalars().all()
            return {"pages_in_sitemap": sum(1 for p in total if p.in_sitemap), "pages_crawled": len(total)}

        return self._record("inspect_sitemap", {}, go)

    def validate_schema(self, url: str) -> list[dict[str, Any]]:
        def go() -> list[dict[str, Any]]:
            page = self.db.execute(select(Page).where(Page.site_id == self.site.id, Page.url == url)).scalar_one_or_none()
            snap = self.db.get(PageSnapshot, page.last_snapshot_id) if page and page.last_snapshot_id else None
            return [{"valid_json": b.get("valid_json"), "types": b.get("types"), "error": b.get("error")}
                    for b in ((snap.extracted if snap else {}).get("jsonld") or [])]

        return self._record("validate_schema", {"url": url}, go)

    def get_search_queries(self, limit: int = 50) -> list[dict[str, Any]]:
        def go() -> list[dict[str, Any]]:
            rows = self.db.execute(select(KeywordQuery).where(KeywordQuery.site_id == self.site.id)
                                   .order_by(KeywordQuery.impressions.desc()).limit(limit)).scalars()
            return [{"evidence_id": f"query:{q.id}", "query": q.query, "page": q.page_url, "clicks": q.clicks, "impressions": q.impressions,
                     "ctr": q.ctr, "position": q.position, "source": q.source} for q in rows]

        return self._record("get_search_queries", {"limit": limit}, go)

    def get_execution_history(self, limit: int = 20) -> list[dict[str, Any]]:
        def go() -> list[dict[str, Any]]:
            rows = self.db.execute(select(ExecutionRun, ChangeSet).join(ChangeSet, ChangeSet.id == ExecutionRun.change_set_id)
                                   .where(ChangeSet.site_id == self.site.id).order_by(ExecutionRun.created_at.desc()).limit(limit)).all()
            return [{"evidence_id": f"execution:{r.id}", "change": c.title, "kind": r.kind, "status": r.status,
                     "finished_at": r.finished_at.isoformat() if r.finished_at else None} for r, c in rows]

        return self._record("get_execution_history", {"limit": limit}, go)

    def get_gsc_metrics(self, page: str | None = None) -> list[dict[str, Any]]:
        def go() -> list[dict[str, Any]]:
            q = select(SearchMetric).where(SearchMetric.site_id == self.site.id)
            if page:
                q = q.where(SearchMetric.page == page)
            return [{"date": m.date.isoformat(), "clicks": m.clicks, "impressions": m.impressions, "position": m.position, "source": m.source}
                    for m in self.db.execute(q.order_by(SearchMetric.date)).scalars()]

        return self._record("get_gsc_metrics", {"page": page}, go)


def start_run(db: Session, *, site: Site, agent: str, task: str, input: dict[str, Any], workflow_run_id: uuid.UUID | None = None,
              gateway: Gateway | None = None, charge: bool = True) -> AgentRun:
    gw = gateway or Gateway()
    if gw.mode == "llm" and charge:
        billing.check_budget(db, site.tenant_id, ESTIMATED_CREDITS_PER_CALL)
    run = AgentRun(tenant_id=site.tenant_id, site_id=site.id, workflow_run_id=workflow_run_id, agent=agent, task=task, input=input,
                   status="running", provider="pending", model="pending", prompt_version="-")
    db.add(run)
    db.flush()
    return run


def finish_run(db: Session, run: AgentRun, result: AIResult[Any], *, evidence_ids: list[str], extra: dict[str, Any] | None = None) -> None:
    out = result.output.model_dump() if isinstance(result.output, BaseModel) else result.output
    run.output = {**out, **(extra or {}), "_meta": {"fallback_used": result.fallback_used, "note": result.note}}
    run.provider, run.model, run.prompt_version = result.provider, result.model, result.prompt_version
    run.input_tokens, run.output_tokens, run.cost_usd, run.latency_ms = result.input_tokens, result.output_tokens, result.cost_usd, result.latency_ms
    run.evidence_ids = evidence_ids
    run.status = "succeeded"
    credits = billing.ai_credit_cost(result.input_tokens, result.output_tokens)
    if credits:
        billing.post(db, run.tenant_id, -credits, reason="ai_usage", idempotency_key=f"agent:{run.id}", ref_type="agent_run",
                     ref_id=str(run.id), allow_negative=True, meta={"model": result.model})
        billing.record_usage(db, run.tenant_id, "ai_input_tokens", result.input_tokens, "agent_run", str(run.id))
        billing.record_usage(db, run.tenant_id, "ai_output_tokens", result.output_tokens, "agent_run", str(run.id))
    run.credits_charged = credits
    run.updated_at = utcnow()


def fail_run(run: AgentRun, error: str) -> None:
    run.status = "failed"
    run.error = error[:1000]


def check_citations(cited: list[str], known: set[str]) -> list[str]:
    unknown = [c for c in cited if c not in known]
    return [f"Unknown evidence IDs cited: {unknown[:5]}"] if unknown else []


_ = AppError
