"""Public (read-only) connector for sites we can crawl but not write to."""

from __future__ import annotations

from typing import Any

from aseo.connectors.base import Capability, ConnectorContext, ResourceState, RollbackResult, unsupported
from aseo.connectors.live_check import fetch_live_fields
from aseo.core.errors import ConnectorError

ACTIONS = ["meta_description", "title", "internal_link", "structured_data", "canonical", "robots", "redirect"]


class PublicConnector:
    provider = "public"

    async def verify_ownership(self, ctx: ConnectorContext) -> dict[str, Any]:
        return {"note": "Public connector cannot verify ownership; use meta tag, DNS or file verification."}

    async def capabilities(self, ctx: ConnectorContext) -> list[Capability]:
        return [unsupported(a, "Read-only public audit: changes are recommendations you apply yourself.") for a in ACTIONS]

    async def discover_pages(self, ctx: ConnectorContext) -> list[str]:
        return []

    async def read_resource(self, ctx: ConnectorContext, url: str) -> ResourceState:
        live = await fetch_live_fields(url)
        return ResourceState(ref={"type": "url", "id": url, "url": url},
                             fields={"meta_description": live.get("meta_description") or "", "title": live.get("title") or ""},
                             version=None, url=url)

    async def prepare_patch(self, ctx, url, action_type, after):  # noqa: ANN001
        raise ConnectorError("Read-only connector", code="unsupported_action")

    async def apply_patch(self, ctx, patch, *, expected_version, change_ref):  # noqa: ANN001
        raise ConnectorError("Read-only connector: no write access", code="unsupported_action")

    async def verify_patch(self, ctx, patch, apply):  # noqa: ANN001
        raise ConnectorError("Read-only connector", code="unsupported_action")

    async def rollback(self, ctx, patch, snapshot, *, current_version, change_ref):  # noqa: ANN001
        return RollbackResult(False, True, "Read-only connector")
