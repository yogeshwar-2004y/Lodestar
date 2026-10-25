"""Shopify connector (Admin GraphQL API).

Supported writes: SEO title / meta description for products and collections (``seo``
input) and pages (``global.title_tag`` / ``global.description_tag`` metafields). Theme
edits are never automated (review-only). Shopify has no conditional writes, so we re-read
``updatedAt`` immediately before writing and refuse if it changed (optimistic check), and
rollback refuses to overwrite a value someone changed after us.
"""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urlsplit

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
from aseo.connectors.live_check import compare, fetch_live_fields, norm
from aseo.core.config import get_settings
from aseo.core.errors import ConnectorError
from aseo.crawler.netguard import BlockedDestination, safe_fetch

SHOP_RE = re.compile(r"^[a-z0-9][a-z0-9-]*\.myshopify\.com$")
SCOPES = ["read_products", "write_products", "read_content", "write_content"]
PATH_RE = re.compile(r"^/(?:[a-z]{2}(?:-[a-z]{2})?/)?(products|collections|pages)/([^/?#]+)")

Q_PRODUCT = "query($q:String!){ products(first:1, query:$q){ nodes{ id handle updatedAt onlineStoreUrl seo{ title description } } } }"
Q_COLLECTION = "query($q:String!){ collections(first:1, query:$q){ nodes{ id handle updatedAt seo{ title description } } } }"
Q_PAGE = ("query($q:String!){ pages(first:1, query:$q){ nodes{ id handle updatedAt "
          "t: metafield(namespace:\"global\", key:\"title_tag\"){ value } d: metafield(namespace:\"global\", key:\"description_tag\"){ value } } } }")
M_PRODUCT = "mutation($p:ProductUpdateInput!){ productUpdate(product:$p){ product{ id updatedAt } userErrors{ field message } } }"
M_COLLECTION = "mutation($c:CollectionInput!){ collectionUpdate(input:$c){ collection{ id updatedAt } userErrors{ field message } } }"
M_METAFIELDS = "mutation($m:[MetafieldsSetInput!]!){ metafieldsSet(metafields:$m){ metafields{ id updatedAt } userErrors{ field message } } }"
FIELD_KEYS = {"meta_description": ("description", "description_tag"), "title": ("title", "title_tag")}


class ShopifyConnector:
    provider = "shopify"

    def _shop(self, ctx: ConnectorContext) -> str:
        shop = str(ctx.config.get("shop", "")).lower()
        if not SHOP_RE.match(shop):
            raise ConnectorError("Invalid shop domain (expected <store>.myshopify.com).", code="connector_not_configured")
        return shop

    async def _gql(self, ctx: ConnectorContext, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        token = ctx.secrets.get("access_token")
        if not token:
            raise ConnectorError("Shopify access token missing.", code="connector_not_configured")
        url = f"https://{self._shop(ctx)}/admin/api/{get_settings().shopify_api_version}/graphql.json"
        try:
            res = await safe_fetch(url, method="POST", json_body={"query": query, "variables": variables or {}}, max_redirects=0, timeout=30,
                                   headers={"X-Shopify-Access-Token": token, "Content-Type": "application/json", "Accept": "application/json"})
        except BlockedDestination as exc:
            raise ConnectorError(f"Shopify host blocked: {exc}") from exc
        if res.status_code in (401, 403):
            raise ConnectorError("Shopify rejected the token or the app lacks a required scope.", code="connector_unauthorized")
        if res.status_code == 429 or res.status_code >= 500:
            raise ConnectorError(f"Shopify returned {res.status_code}", retryable=True)
        body = json.loads(res.body or b"{}")
        errors = body.get("errors") or []
        if any((e.get("extensions") or {}).get("code") == "THROTTLED" for e in errors if isinstance(e, dict)):
            raise ConnectorError("Shopify API throttled", retryable=True)
        if errors:
            raise ConnectorError(f"Shopify GraphQL error: {str(errors)[:200]}")
        return body.get("data") or {}

    async def verify_ownership(self, ctx: ConnectorContext) -> dict[str, Any]:
        data = await self._gql(ctx, "{ shop{ name myshopifyDomain primaryDomain{ host url } } }")
        shop = data.get("shop") or {}
        primary = ((shop.get("primaryDomain") or {}).get("host") or "").lower()
        site_host = ctx.site_host.split(":")[0].lower()
        match = primary in (site_host, f"www.{site_host}") or site_host in (primary, f"www.{primary}") or site_host == shop.get("myshopifyDomain")
        return {"shop": shop.get("myshopifyDomain"), "primary_domain": primary, "domain_match": match}

    async def capabilities(self, ctx: ConnectorContext) -> list[Capability]:
        pre = ["Authorized app with read/write_products and read/write_content", "Site ownership verified", "URL is a product, collection or page"]
        return [
            Capability("meta_description", True, "direct", True, pre, SCOPES, "Products & collections: SEO description. Pages: global.description_tag."),
            Capability("title", True, "direct", True, pre, SCOPES, "SEO title (not the product name)."),
            unsupported("theme_edit", "Theme changes are review-only and never automated."),
            unsupported("structured_data", "Recommendation only in V1."),
            unsupported("internal_link", "Recommendation only in V1."),
            unsupported("redirect", "Restricted: manage URL redirects manually."),
        ]

    async def discover_pages(self, ctx: ConnectorContext) -> list[str]:
        return []

    def _locate(self, url: str) -> tuple[str, str]:
        m = PATH_RE.match(urlsplit(url).path or "/")
        if not m:
            raise ConnectorError("Only product, collection and page URLs can be edited through Shopify.", code="unsupported_resource")
        return m.group(1), m.group(2)

    async def read_resource(self, ctx: ConnectorContext, url: str) -> ResourceState:
        kind, handle = self._locate(url)
        q = {"products": Q_PRODUCT, "collections": Q_COLLECTION, "pages": Q_PAGE}[kind]
        data = await self._gql(ctx, q, {"q": f"handle:{handle}"})
        nodes = (data.get(kind) or {}).get("nodes") or []
        if not nodes:
            raise ConnectorError(f"No Shopify {kind[:-1]} with handle '{handle}'.", code="connector_not_found")
        n = nodes[0]
        if kind == "pages":
            fields = {"title": ((n.get("t") or {}).get("value") or ""), "meta_description": ((n.get("d") or {}).get("value") or "")}
        else:
            fields = {"title": (n.get("seo") or {}).get("title") or "", "meta_description": (n.get("seo") or {}).get("description") or ""}
        return ResourceState(ref={"type": kind[:-1], "id": n["id"], "url": url, "handle": handle}, fields=fields, version=n.get("updatedAt"), url=url)

    async def prepare_patch(self, ctx: ConnectorContext, url: str, action_type: str, after: dict[str, Any]) -> PreparedPatch:
        if action_type not in FIELD_KEYS:
            raise ConnectorError(f"Shopify connector cannot write '{action_type}'.", code="unsupported_action")
        state = await self.read_resource(ctx, url)
        return PreparedPatch(ref=state.ref, before={action_type: state.fields[action_type]}, after={action_type: after[action_type]},
                             resource_version=state.version)

    async def _write(self, ctx: ConnectorContext, ref: dict[str, Any], values: dict[str, str]) -> str | None:
        if ref["type"] == "page":
            mf = [{"ownerId": ref["id"], "namespace": "global", "key": FIELD_KEYS[k][1], "type": "single_line_text_field" if k == "title" else "multi_line_text_field", "value": v}
                  for k, v in values.items()]
            data = await self._gql(ctx, M_METAFIELDS, {"m": mf})
            result = data.get("metafieldsSet") or {}
            stamp = ((result.get("metafields") or [{}])[0]).get("updatedAt")
        else:
            seo = {FIELD_KEYS[k][0]: v for k, v in values.items()}
            if ref["type"] == "product":
                data = await self._gql(ctx, M_PRODUCT, {"p": {"id": ref["id"], "seo": seo}})
                result = data.get("productUpdate") or {}
                stamp = (result.get("product") or {}).get("updatedAt")
            else:
                data = await self._gql(ctx, M_COLLECTION, {"c": {"id": ref["id"], "seo": seo}})
                result = data.get("collectionUpdate") or {}
                stamp = (result.get("collection") or {}).get("updatedAt")
        if result.get("userErrors"):
            raise ConnectorError(f"Shopify rejected the update: {result['userErrors'][0].get('message')}", code="connector_validation")
        return stamp

    async def apply_patch(self, ctx: ConnectorContext, patch: dict[str, Any], *, expected_version: str | None, change_ref: str) -> ApplyResult:
        current = await self.read_resource(ctx, patch["resource"]["url"])
        if expected_version and current.version != expected_version:
            raise StaleResourceError("The Shopify resource changed after the patch was prepared.")
        stamp = await self._write(ctx, patch["resource"], patch["after"])
        state = await self.read_resource(ctx, patch["resource"]["url"])
        return ApplyResult(applied=True, live=True, resource_version=state.version or stamp,
                           previous={k: current.fields.get(k) for k in patch["after"]}, response={"updated_at": stamp})

    async def verify_patch(self, ctx: ConnectorContext, patch: dict[str, Any], apply: dict[str, Any]) -> VerifyResult:
        state = await self.read_resource(ctx, patch["resource"]["url"])
        api_ok, api_mm = compare(patch["after"], state.fields)
        live = await fetch_live_fields(patch["resource"]["url"])
        live_ok, live_mm = compare(patch["after"], live)
        return VerifyResult(api_ok and live_ok, api_ok and not live_ok, "admin_api_reread+live_html", patch["after"],
                            {"resource": {k: state.fields.get(k) for k in patch["after"]}, "live_html": {k: live.get(k) for k in patch["after"]}},
                            {"api_mismatch": api_mm, "live_mismatch": live_mm, "fetched_url": live.get("fetched_url"),
                             "note": "Shopify storefront caches can delay visible changes by a few minutes."})

    async def rollback(self, ctx: ConnectorContext, patch: dict[str, Any], snapshot: dict[str, Any], *, current_version: str | None, change_ref: str) -> RollbackResult:
        state = await self.read_resource(ctx, patch["resource"]["url"])
        if any(norm(state.fields.get(k)) != norm(v) for k, v in patch["after"].items()):
            return RollbackResult(False, True, "The field was changed in Shopify after our write. Review it manually before restoring.")
        await self._write(ctx, patch["resource"], snapshot["previous_value"])
        after = await self.read_resource(ctx, patch["resource"]["url"])
        return RollbackResult(True, False, "Previous value restored in Shopify.", resource_version=after.version)
