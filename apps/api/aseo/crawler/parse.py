"""HTML and sitemap extraction. Crawled content is untrusted data: we extract structured
fields only and never execute or interpret page content as instructions."""

from __future__ import annotations

import gzip
import json
import re
from typing import Any

from defusedxml import ElementTree as SafeET
from selectolax.parser import HTMLParser

from aseo.crawler.urls import InvalidURL, normalize_url

_WS = re.compile(r"\s+")


def _clean(text: str | None, limit: int = 2000) -> str | None:
    if text is None:
        return None
    value = _WS.sub(" ", text).strip()
    return value[:limit]


def extract_html(html: str, page_url: str) -> dict[str, Any]:
    tree = HTMLParser(html)
    head = tree.head
    out: dict[str, Any] = {}

    titles = [_clean(n.text()) for n in tree.css("head title")] or [_clean(n.text()) for n in tree.css("title")]
    out["title"] = titles[0] if titles else None
    out["title_count"] = len(titles)

    metas: dict[str, list[str]] = {}
    for node in tree.css("meta"):
        name = (node.attributes.get("name") or node.attributes.get("property") or "").strip().lower()
        if name:
            metas.setdefault(name, []).append(_clean(node.attributes.get("content") or "", 1000) or "")
    descriptions = metas.get("description", [])
    out["meta_description"] = descriptions[0] if descriptions else None
    out["meta_description_count"] = len(descriptions)
    robots_values = metas.get("robots", []) + metas.get("googlebot", [])
    out["robots_meta"] = ", ".join(v for v in robots_values if v) or None
    out["og"] = {k: v[0] for k, v in metas.items() if k.startswith("og:")}
    out["viewport"] = (metas.get("viewport") or [None])[0]

    canonicals = []
    hreflang = []
    for link in tree.css("link"):
        rel = (link.attributes.get("rel") or "").lower().split()
        href = link.attributes.get("href")
        if not href:
            continue
        if "canonical" in rel:
            try:
                canonicals.append(normalize_url(href, page_url, strip_tracking=False))
            except InvalidURL:
                canonicals.append(href)
        if "alternate" in rel and link.attributes.get("hreflang"):
            hreflang.append({"hreflang": link.attributes.get("hreflang"), "href": href})
    out["canonical"] = canonicals[0] if canonicals else None
    out["canonical_count"] = len(canonicals)
    out["hreflang"] = hreflang

    headings: list[dict[str, Any]] = []
    for node in tree.css("h1, h2, h3, h4, h5, h6"):
        headings.append({"level": int(node.tag[1]), "text": _clean(node.text(), 300)})
    out["headings"] = headings[:200]
    out["h1"] = [h["text"] for h in headings if h["level"] == 1]

    links: list[dict[str, Any]] = []
    for a in tree.css("a[href]"):
        href = (a.attributes.get("href") or "").strip()
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:", "data:")):
            continue
        try:
            target = normalize_url(href, page_url)
        except InvalidURL:
            continue
        rel = (a.attributes.get("rel") or "").lower()
        links.append({"href": target, "text": _clean(a.text(), 200), "nofollow": "nofollow" in rel})
    out["links"] = links[:2000]

    images = []
    for img in tree.css("img"):
        src = img.attributes.get("src") or img.attributes.get("data-src")
        alt = img.attributes.get("alt")
        images.append({"src": src, "alt": alt if alt is None else _clean(alt, 300), "has_alt_attr": "alt" in img.attributes})
    out["images"] = images[:500]

    jsonld: list[dict[str, Any]] = []
    for script in tree.css('script[type="application/ld+json"]'):
        raw = script.text() or ""
        try:
            parsed = json.loads(raw)
            jsonld.append({"valid_json": True, "data": parsed, "types": _ld_types(parsed)})
        except json.JSONDecodeError as exc:
            jsonld.append({"valid_json": False, "error": str(exc)[:200], "raw_excerpt": raw[:300]})
    out["jsonld"] = jsonld

    html_node = tree.css_first("html")
    out["lang"] = html_node.attributes.get("lang") if html_node else None

    first_paragraph = None
    for node in tree.css("main p, article p, p"):
        t = _clean(node.text(), 600)
        if t and len(t) >= 40:
            first_paragraph = t
            break
    out["first_paragraph"] = first_paragraph

    body = tree.body
    text = ""
    if body is not None:
        for bad in body.css("script, style, noscript, template, svg"):
            bad.decompose()
        text = _clean(body.text(separator=" "), 2_000_000) or ""
    words = len(text.split()) if text else 0
    out["word_count"] = words
    out["text_excerpt"] = text[:1500]
    script_count = len(tree.css("script[src]"))
    root_div = tree.css_first("#root, #__next, #app")
    out["needs_js_render"] = bool(words < 50 and (script_count >= 3 or root_div is not None))
    out["head_present"] = head is not None
    return out


def _ld_types(data: Any) -> list[str]:
    types: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            t = node.get("@type")
            if isinstance(t, str):
                types.append(t)
            elif isinstance(t, list):
                types.extend(str(x) for x in t)
            for key in ("@graph", "mainEntity", "itemListElement"):
                if key in node:
                    walk(node[key])
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(data)
    return types


def parse_sitemap(content: bytes) -> tuple[list[str], list[str]]:
    """Returns (page_urls, child_sitemaps). Safe against XXE/billion-laughs via defusedxml."""
    if content[:2] == b"\x1f\x8b":
        content = gzip.decompress(content)[:50_000_000]
    try:
        root = SafeET.fromstring(content)
    except Exception:  # noqa: BLE001 — malformed sitemap is a finding, not a crash
        return [], []
    tag = root.tag.split("}")[-1].lower()
    locs = [(el.text or "").strip() for el in root.iter() if el.tag.split("}")[-1].lower() == "loc"]
    locs = [loc for loc in locs if loc]
    if tag == "sitemapindex":
        return [], locs
    return locs, []
