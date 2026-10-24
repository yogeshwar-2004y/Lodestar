"""Risk scoring and policy evaluation (pure, deterministic, unit-tested).

Modes:
* observe   — monitor and recommend only; no writes at all.
* assist    — (default) every write needs human approval.
* autopilot — explicit opt-in; whitelisted low-risk action types inside the configured path
              scope may auto-execute when every safety check passes.

AI confidence is never an input here: a model cannot authorize a production write.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

BASE_RISK = {
    "meta_description": 0.15,
    "title": 0.30,
    "internal_link": 0.50,
    "structured_data": 0.50,
    "content_publish": 0.80,
    "canonical": 0.90,
    "redirect": 0.90,
    "robots": 0.95,
    "delete": 1.0,
}
# Never executable in V1 (recommendation only).
RESTRICTED = {"canonical", "robots", "redirect", "delete"}
# Executable only with human (editorial) approval, regardless of mode.
REVIEW_REQUIRED = {"internal_link", "structured_data", "content_publish"}
# The only action types autopilot may ever auto-execute.
AUTO_ELIGIBLE = {"meta_description", "title"}


@dataclass
class PolicyInput:
    action_type: str
    url_path: str
    is_homepage: bool
    replaces_existing_value: bool
    bulk_size: int
    capability_supported: bool
    write_mode: str
    rollback_supported: bool
    site_verified: bool
    connector_connected: bool
    kill_switch: bool
    mode: str  # observe|assist|autopilot
    paused: bool
    auto_actions: list[str]
    path_scope: list[str]
    max_risk_score: float
    max_auto_changes_per_day: int
    auto_changes_today: int
    validation_passed: bool
    connector_mode: str = "live"  # live|fixture
    production: bool = False


@dataclass
class Check:
    name: str
    passed: bool
    detail: str


@dataclass
class PolicyDecision:
    decision: str  # deny | require_approval | auto_approve
    risk_score: float
    risk_level: str
    reasons: list[str]
    checks: list[Check] = field(default_factory=list)
    rollback_guaranteed: bool = False

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d


def risk(inp: PolicyInput) -> tuple[float, str]:
    score = BASE_RISK.get(inp.action_type, 0.7)
    if inp.is_homepage:
        score += 0.20  # highest-visibility page: conservative by default
    if inp.replaces_existing_value:
        score += 0.05
    if not inp.rollback_supported:
        score += 0.20
    if inp.bulk_size > 5:
        score += 0.20
    score = round(min(1.0, score), 2)
    level = "low" if score < 0.3 else "medium" if score < 0.6 else "high"
    return score, level


def evaluate(inp: PolicyInput) -> PolicyDecision:
    score, level = risk(inp)
    checks: list[Check] = []

    def check(name: str, ok: bool, detail: str) -> bool:
        checks.append(Check(name, ok, detail))
        return ok

    hard_ok = all([
        check("kill_switch_off", not inp.kill_switch, "Emergency kill switch is engaged" if inp.kill_switch else "Kill switch off"),
        check("not_observe_mode", inp.mode != "observe", "Observe mode: recommendations only" if inp.mode == "observe" else f"Mode: {inp.mode}"),
        check("action_not_restricted", inp.action_type not in RESTRICTED,
              f"'{inp.action_type}' changes are restricted to manual handling in V1" if inp.action_type in RESTRICTED else "Action allowed"),
        check("connector_supports_action", inp.capability_supported,
              "Connector cannot perform this write — it stays a recommendation" if not inp.capability_supported else f"Write mode: {inp.write_mode}"),
        check("connector_connected", inp.connector_connected, "Connector connected" if inp.connector_connected else "Connector not connected"),
        check("site_verified", inp.site_verified, "Site ownership verified" if inp.site_verified else "Site ownership not verified — no writes to unverified sites"),
        check("deterministic_validation", inp.validation_passed, "Validation passed" if inp.validation_passed else "Validation failed"),
        check("fixture_not_in_production", not (inp.production and inp.connector_mode == "fixture"),
              "Fixture connectors are refused in production" if inp.production and inp.connector_mode == "fixture" else "Connector mode ok"),
    ])
    rollback_guaranteed = inp.rollback_supported and inp.write_mode == "direct"
    if not hard_ok:
        failed = [c.detail for c in checks if not c.passed]
        return PolicyDecision("deny", score, level, failed, checks, rollback_guaranteed)

    auto_reasons: list[str] = []
    in_scope = not inp.path_scope or any(inp.url_path.startswith(p) for p in inp.path_scope)
    auto_ok = all([
        check("autopilot_enabled", inp.mode == "autopilot", "Autopilot enabled" if inp.mode == "autopilot" else "Assist mode: human approval required"),
        check("automation_not_paused", not inp.paused, "Automation paused" if inp.paused else "Automation active"),
        check("action_auto_eligible", inp.action_type in AUTO_ELIGIBLE and inp.action_type not in REVIEW_REQUIRED,
              "Action type eligible for automation" if inp.action_type in AUTO_ELIGIBLE else "Action type always requires review"),
        check("action_whitelisted", inp.action_type in inp.auto_actions,
              "Whitelisted by site policy" if inp.action_type in inp.auto_actions else "Not whitelisted in site policy"),
        check("path_in_scope", in_scope, f"{inp.url_path} within autopilot scope" if in_scope else f"{inp.url_path} outside autopilot scope"),
        check("risk_within_limit", score <= inp.max_risk_score, f"Risk {score} vs limit {inp.max_risk_score}"),
        check("daily_limit", inp.auto_changes_today < inp.max_auto_changes_per_day,
              f"{inp.auto_changes_today}/{inp.max_auto_changes_per_day} automatic changes today"),
        check("rollback_supported", rollback_guaranteed, "Automatic rollback available" if rollback_guaranteed else "Rollback not guaranteed"),
        check("not_bulk", inp.bulk_size <= 5, "Single/small change" if inp.bulk_size <= 5 else "Bulk edits need review"),
    ])
    if auto_ok:
        return PolicyDecision("auto_approve", score, level, ["All autopilot checks passed"], checks, rollback_guaranteed)
    auto_reasons = [c.detail for c in checks[8:] if not c.passed]
    return PolicyDecision("require_approval", score, level, auto_reasons or ["Human approval required"], checks, rollback_guaranteed)
