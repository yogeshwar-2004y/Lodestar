"""WordPress connector.

Talks to the Lodestar companion plugin (integrations/wordpress/lodestar-companion) through
the authenticated WordPress REST API using an Application Password for a least-privilege
user. The plugin normalises SEO fields across Yoast, Rank Math, AIOSEO or its own storage,
records a revision history, and enforces optimistic concurrency via ``expected_version``.
"""

from __future__ import annotations

import base64
import json
from typing import Any
from urllib.parse import quote

from aseo.connectors.base import (
    ApplyResult,
    Capability,
    ConnectorContext,
    PreparedPatch,
    ResourceState,
    RollbackResult,
    StaleResourceError,
    VerifyResult,
    unsupported,
)
from aseo.connectors.live_check import compare, fetch_live_fields
from aseo.core.errors import ConnectorError
from aseo.crawler.netguard import BlockedDestination, safe_fetch

NAMESPACE = "lodestar/v1"
SUPPORTED_FIELDS = {"meta_description": "description", "title": "title"}


class WordPressConnector:
    provider = "wordpress"

    def _api_root(self, ctx: ConnectorContext) -> str:
        root = ctx.config.get("rest_url") or ctx.site_base_url.rstrip("/") + "/wp-json/"
        return root if root.endswith("/") else root + "/"

    def _auth(self, ctx: ConnectorContext) -> dict[str, str]:
        user = ctx.config.get("username")
        pw = ctx.secrets.get("app_password")
        if not user or not pw:
            raise ConnectorError("WordPress connector is missing username or application password.", code="connector_not_configured")
        token = base64.b64encode(f"{user}:{pw}".encode()).decode()
        return {"Authorization": f"Basic {token}"}

    async def _call(self, ctx: ConnectorContext, method: str, path: str, body: Any = None) -> dict[str, Any]:
        url = self._api_root(ctx) + path
        try:
            res = await safe_fetch(url, method=method, headers={**self._auth(ctx), "Accept": "application/json"},
                                   json_body=body, max_redirects=0 if method != "GET" else 3, timeout=20)
        except BlockedDestination as exc:
            raise ConnectorError(f"WordPress URL blocked by network policy: {exc}", code="destination_blocked") from exc
        except Exception as exc:  # noqa: BLE001
            raise ConnectorError(f"WordPress request failed: {type(exc).__name__}", retryable=True) from exc
        try:
            data = json.loads(res.body or b"{}")
        except json.JSONDecodeError:
            data = {"raw": res.text[:300]}
        if res.status_code == 409:
            raise StaleResourceError("The WordPress resource changed since the patch was prepared.", details=_safe(data))
        if res.status_code == 429 or res.status_code >= 500:
            raise ConnectorError(f"WordPress returned {res.status_code}", retryable=True, details=_safe(data))
        if res.status_code in (401, 403):
            raise ConnectorError("WordPress rejected the credentials or the user lacks permission.", code="connector_unauthorized",
                                 details=_safe(data))
        if res.status_code == 404:
            raise ConnectorError("Resource or companion plugin endpoint not found (is the plugin active?).", code="connector_not_found",
                                 details=_safe(data))
        if res.status_code >= 400:
            raise ConnectorError(f"WordPress returned {res.status_code}", details=_safe(data))
        return data if isinstance(data, dict) else {"data": data}

    # -------------------------------------------------------------- protocol

    async def verify_ownership(self, ctx: ConnectorContext) -> dict[str, Any]:
        status = await self._call(ctx, "GET", f"{NAMESPACE}/status")
        return {"plugin_version": status.get("plugin_version"), "verification_token": status.get("verification_token"),
                "seo_plugin": status.get("seo_plugin"), "site_url": status.get("site_url")}

    async def capabilities(self, ctx: ConnectorContext) -> list[Capability]:
        perms = ["Application Password for a user with the 'Lodestar SEO Agent' role (edit_posts, edit_pages, edit_published_*)"]
        pre = ["Companion plugin active", "Site ownership verified", "Resource resolvable from URL"]
        return [
            Capability("meta_description", True, "direct", True, pre, perms, "Writes via companion plugin; previous value kept in revision history."),
            Capability("title", True, "direct", True, pre, perms, "SEO title override (not the post title)."),
            unsupported("internal_link", "Recommendation only in V1 — requires editorial review of post content."),
            unsupported("structured_data", "Recommendation only in V1 — review-first workflow."),
            unsupported("canonical", "Restricted: canonical changes are never automated in V1."),
            unsupported("robots", "Restricted: robots changes are never automated in V1."),
            unsupported("redirect", "Restricted: redirects require manual review."),
        ]

    async def discover_pages(self, ctx: ConnectorContext) -> list[str]:
        data = await self._call(ctx, "GET", f"{NAMESPACE}/resources?per_page=100")
        return [r["permalink"] for r in data.get("resources", []) if r.get("permalink")]

    async def read_resource(self, ctx: ConnectorContext, url: str) -> ResourceState:
        data = await self._call(ctx, "GET", f"{NAMESPACE}/resolve?url={quote(url, safe='')}")
        seo = data.get("seo", {})
        return ResourceState(
            ref={"type": data.get("type"), "id": data.get("id"), "url": data.get("permalink") or url},
            fields={"meta_description": seo.get("description") or "", "title": seo.get("title") or ""},
            version=data.get("version"),
            url=data.get("permalink") or url,
            extra={"seo_plugin": data.get("seo_plugin")},
        )

    async def prepare_patch(self, ctx: ConnectorContext, url: str, action_type: str, after: dict[str, Any]) -> PreparedPatch:
        if action_type not in SUPPORTED_FIELDS:
            raise ConnectorError(f"WordPress connector cannot write '{action_type}'.", code="unsupported_action")
        state = await self.read_resource(ctx, url)
        field = action_type
        warnings = []
        if state.extra.get("seo_plugin") in (None, "none"):
            warnings.append("No SEO plugin detected; the companion plugin will output the tag itself.")
        return PreparedPatch(
            ref=state.ref,
            before={field: state.fields.get(field, "")},
            after={field: after[field]},
            resource_version=state.version,
            warnings=warnings,
            preview={"seo_plugin": state.extra.get("seo_plugin")},
        )

    async def apply_patch(self, ctx: ConnectorContext, patch: dict[str, Any], *, expected_version: str | None, change_ref: str) -> ApplyResult:
        ref = patch["resource"]
        fields = {SUPPORTED_FIELDS[k]: v for k, v in patch["after"].items()}
        data = await self._call(ctx, "POST", f"{NAMESPACE}/seo/{int(ref['id'])}",
                                {"fields": fields, "expected_version": expected_version, "change_ref": change_ref})
        return ApplyResult(
            applied=True,
            live=True,
            resource_version=data.get("version"),
            previous={k: (data.get("previous") or {}).get(SUPPORTED_FIELDS[k]) for k in patch["after"]},
            response={"revision_id": data.get("revision_id"), "version": data.get("version")},
        )

    async def verify_patch(self, ctx: ConnectorContext, patch: dict[str, Any], apply: dict[str, Any]) -> VerifyResult:
        url = patch["resource"]["url"]
        state = await self.read_resource(ctx, url)
        stored = {k: state.fields.get(k) for k in patch["after"]}
        api_ok, api_mismatch = compare(patch["after"], stored)
        live = await fetch_live_fields(url)
        live_ok, live_mismatch = compare(patch["after"], live)
        return VerifyResult(
            verified=api_ok and live_ok,
            pending=api_ok and not live_ok,  # stored but not visible yet (page cache?)
            method="resource_reread+live_html",
            expected=patch["after"],
            observed={"resource": stored, "live_html": {k: live.get(k) for k in patch["after"]}},
            details={"api_mismatch": api_mismatch, "live_mismatch": live_mismatch, "live_status": live.get("status_code"),
                     "cache_headers": live.get("cache_headers"), "fetched_url": live.get("fetched_url")},
        )

    async def rollback(self, ctx: ConnectorContext, patch: dict[str, Any], snapshot: dict[str, Any], *, current_version: str | None, change_ref: str) -> RollbackResult:
        ref = patch["resource"]
        fields = {SUPPORTED_FIELDS[k]: v for k, v in snapshot["previous_value"].items()}
        try:
            data = await self._call(ctx, "POST", f"{NAMESPACE}/seo/{int(ref['id'])}",
                                    {"fields": fields, "expected_version": current_version, "change_ref": change_ref, "is_rollback": True})
        except StaleResourceError:
            return RollbackResult(False, True, "The field was edited by someone else after our change. Review it manually before restoring.")
        return RollbackResult(True, False, "Previous value restored.", {"revision_id": data.get("revision_id")}, data.get("version"))


def _safe(data: Any) -> Any:
    if isinstance(data, dict):
        return {k: v for k, v in data.items() if k in ("code", "message", "data", "current_version")}
    return None
