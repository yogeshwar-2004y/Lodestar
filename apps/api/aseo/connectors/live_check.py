"""Live HTML verification shared by connectors: fetch the public page through the SSRF guard
and compare the rendered tag values with what we wrote."""

from __future__ import annotations

import re
import secrets
from typing import Any
from urllib.parse import urlencode, urlsplit, urlunsplit

from aseo.crawler.netguard import safe_fetch
from aseo.crawler.parse import extract_html

_WS = re.compile(r"\s+")


def norm(value: Any) -> str:
    return _WS.sub(" ", str(value or "")).strip()


async def fetch_live_fields(url: str) -> dict[str, Any]:
    parts = urlsplit(url)
    nonce = secrets.token_hex(4)
    query = (parts.query + "&" if parts.query else "") + urlencode({"lodestar_verify": nonce})
    bust_url = urlunsplit((parts.scheme, parts.netloc, parts.path, query, ""))
    res = await safe_fetch(bust_url, headers={"Cache-Control": "no-cache", "Pragma": "no-cache"})
    ex = extract_html(res.text, res.final_url) if res.status_code == 200 else {}
    return {
        "status_code": res.status_code,
        "fetched_url": bust_url,
        "meta_description": ex.get("meta_description"),
        "title": ex.get("title"),
        "meta_description_count": ex.get("meta_description_count"),
        "cache_headers": {k: res.headers.get(k) for k in ("cache-control", "age", "x-cache", "cf-cache-status") if res.headers.get(k)},
    }


def compare(expected: dict[str, Any], observed: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    mismatches = {}
    for field, value in expected.items():
        if norm(observed.get(field)) != norm(value):
            mismatches[field] = {"expected": value, "observed": observed.get(field)}
    return not mismatches, mismatches
