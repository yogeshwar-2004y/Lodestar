"""Deterministic SEO rule engine.

Rules consume a crawl dataset (pages + link graph + sitemap set) and produce findings with
evidence. Two kinds are kept explicitly separate:

* ``deterministic`` — objectively verifiable defects (missing tag, 404, noindex in sitemap…)
* ``heuristic`` — opportunities based on guidelines (length ranges, thin content…)

The health score is an INTERNAL DIAGNOSTIC — it is not a Google score and does not predict
rankings. See docs/scoring.md.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from aseo.core.security import sha256_hex

SEVERITY_POINTS = {"critical": 25.0, "high": 12.0, "medium": 6.0, "low": 2.0, "info": 0.0}
HEURISTIC_FACTOR = 0.5
SCORE_METHODOLOGY = (
    "Internal diagnostic score (0-100), not a Google metric and not a ranking prediction. "
    "Starts at 100; each rule with affected pages subtracts severity points "
    "(critical 25, high 12, medium 6, low 2, info 0) x rule weight x coverage, where "
    "coverage = sqrt(affected_pages / crawled_pages) capped at 1. Heuristic rules count 50%. "
    "Category scores use the same formula restricted to that category."
)


@dataclass
class PageData:
    url: str
    status_code: int
    final_url: str
    depth: int
    in_sitemap: bool
    redirect_chain: list[dict[str, Any]]
    extracted: dict[str, Any]
    headers: dict[str, str]
    elapsed_ms: int
    page_id: str | None = None
    snapshot_id: str | None = None
    blocked_by_robots: bool = False

    @property
    def is_html_ok(self) -> bool:
        return self.status_code == 200 and bool(self.extracted)

    @property
    def robots_directives(self) -> str:
        meta = (self.extracted.get("robots_meta") or "").lower()
        header = (self.headers.get("x-robots-tag") or "").lower()
        return f"{meta},{header}"

    @property
    def noindex(self) -> bool:
        return "noindex" in self.robots_directives or "none" in self.robots_directives.split(",")

    @property
    def indexable(self) -> bool:
        if not self.is_html_ok or self.noindex:
            return False
        canon = self.extracted.get("canonical")
        return not canon or canon == self.url or canon == self.final_url


@dataclass
class Dataset:
    site_host: str
    pages: list[PageData]
    sitemap_urls: set[str]
    sitemap_files: list[str]
    robots_found: bool

    def __post_init__(self) -> None:
        self.by_url = {p.url: p for p in self.pages}


@dataclass
class Occurrence:
    url: str
    evidence: dict[str, Any]
    page_id: str | None = None
    snapshot_id: str | None = None


@dataclass
class FindingResult:
    rule_key: str
    title: str
    summary: str
    occurrences: list[Occurrence]
    group_key: str = ""  # distinguishes multiple findings of the same rule (e.g. duplicate groups)
    evidence: dict[str, Any] = field(default_factory=dict)

    def fingerprint(self) -> str:
        return sha256_hex(f"{self.rule_key}|{self.group_key}")


@dataclass
class Rule:
    key: str
    category: str  # metadata|content|indexability|links|structured_data|media|performance|crawlability
    title: str
    description: str
    severity: str
    kind: str  # deterministic|heuristic
    remediation: str
    weight: float = 1.0
    fix_action: str | None = None
    check: Callable[[Dataset], list[FindingResult]] = field(default=lambda d: [], repr=False)


RULES: dict[str, Rule] = {}


def rule(**kw: Any) -> Callable[[Callable[[Dataset], list[FindingResult]]], Callable[[Dataset], list[FindingResult]]]:
    def deco(fn: Callable[[Dataset], list[FindingResult]]) -> Callable[[Dataset], list[FindingResult]]:
        r = Rule(check=fn, **kw)
        RULES[r.key] = r
        return fn

    return deco


def _occ(p: PageData, **evidence: Any) -> Occurrence:
    return Occurrence(url=p.url, evidence=evidence, page_id=p.page_id, snapshot_id=p.snapshot_id)


def _single(key: str, occ: list[Occurrence], noun: str) -> list[FindingResult]:
    if not occ:
        return []
    r = RULES[key]
    return [FindingResult(key, r.title, f"{len(occ)} {noun}{'s' if len(occ) != 1 else ''} affected.", occ)]


def _html_pages(d: Dataset, indexable_only: bool = False) -> list[PageData]:
    return [p for p in d.pages if p.is_html_ok and (p.indexable or not indexable_only)]


# ------------------------------------------------------------------ metadata


@rule(key="missing_title", category="metadata", title="Missing <title> tag", severity="high", kind="deterministic",
      description="The page has no title element or the title is empty.",
      remediation="Add a unique, descriptive <title> that reflects the page's primary topic.", fix_action="title")
def _missing_title(d: Dataset) -> list[FindingResult]:
    return _single("missing_title", [_occ(p, title=p.extracted.get("title")) for p in _html_pages(d) if not p.extracted.get("title")], "page")


@rule(key="title_length", category="metadata", title="Title length outside 30-60 characters", severity="low", kind="heuristic",
      description="Very short or very long titles may be truncated or under-describe the page in search results.",
      remediation="Aim for a concise title of roughly 30-60 characters that leads with the main topic.", fix_action="title")
def _title_length(d: Dataset) -> list[FindingResult]:
    occ = []
    for p in _html_pages(d, True):
        t = p.extracted.get("title")
        if t and not 30 <= len(t) <= 60:
            occ.append(_occ(p, title=t, length=len(t)))
    return _single("title_length", occ, "page")


@rule(key="duplicate_title", category="metadata", title="Duplicate titles", severity="medium", kind="deterministic",
      description="Multiple indexable pages share the same title.",
      remediation="Give each indexable page a unique title.", fix_action="title")
def _duplicate_title(d: Dataset) -> list[FindingResult]:
    groups: dict[str, list[PageData]] = defaultdict(list)
    for p in _html_pages(d, True):
        t = (p.extracted.get("title") or "").strip().lower()
        if t:
            groups[t].append(p)
    out = []
    for title, pages in groups.items():
        if len(pages) > 1:
            out.append(FindingResult("duplicate_title", f"Duplicate title on {len(pages)} pages",
                                     f'"{pages[0].extracted.get("title")}" is used by {len(pages)} pages.',
                                     [_occ(p, title=p.extracted.get("title")) for p in pages], group_key=title,
                                     evidence={"title": pages[0].extracted.get("title")}))
    return out


@rule(key="missing_meta_description", category="metadata", title="Missing meta description", severity="medium", kind="deterministic",
      description="The page has no meta description (or it is empty). Search engines may generate a snippet from page text instead.",
      remediation="Write a unique meta description (about 70-160 characters) summarising the page for searchers.",
      fix_action="meta_description", weight=1.0)
def _missing_desc(d: Dataset) -> list[FindingResult]:
    occ = [_occ(p, meta_description=p.extracted.get("meta_description"), title=p.extracted.get("title"))
           for p in _html_pages(d, True) if not (p.extracted.get("meta_description") or "").strip()]
    return _single("missing_meta_description", occ, "page")


@rule(key="meta_description_length", category="metadata", title="Meta description length outside 70-160 characters",
      severity="low", kind="heuristic",
      description="Very short descriptions under-inform searchers; very long ones are often truncated.",
      remediation="Rewrite the description to roughly 70-160 characters.", fix_action="meta_description")
def _desc_len(d: Dataset) -> list[FindingResult]:
    occ = []
    for p in _html_pages(d, True):
        m = (p.extracted.get("meta_description") or "").strip()
        if m and not 70 <= len(m) <= 160:
            occ.append(_occ(p, meta_description=m, length=len(m)))
    return _single("meta_description_length", occ, "page")


@rule(key="duplicate_meta_description", category="metadata", title="Duplicate meta descriptions", severity="low",
      kind="deterministic", description="Multiple indexable pages share the same meta description.",
      remediation="Write a unique description for each page.", fix_action="meta_description")
def _dup_desc(d: Dataset) -> list[FindingResult]:
    groups: dict[str, list[PageData]] = defaultdict(list)
    for p in _html_pages(d, True):
        m = (p.extracted.get("meta_description") or "").strip().lower()
        if m:
            groups[m].append(p)
    return [
        FindingResult("duplicate_meta_description", f"Duplicate meta description on {len(ps)} pages",
                      f"{len(ps)} pages share one description.", [_occ(p, meta_description=p.extracted.get("meta_description")) for p in ps],
                      group_key=k)
        for k, ps in groups.items() if len(ps) > 1
    ]


@rule(key="missing_viewport", category="metadata", title="Missing viewport meta tag", severity="medium", kind="deterministic",
      description="Without a viewport meta tag, mobile browsers render the page at desktop width.",
      remediation='Add <meta name="viewport" content="width=device-width, initial-scale=1">.')
def _viewport(d: Dataset) -> list[FindingResult]:
    return _single("missing_viewport", [_occ(p) for p in _html_pages(d) if not p.extracted.get("viewport")], "page")


@rule(key="missing_lang", category="metadata", title="Missing html lang attribute", severity="low", kind="deterministic",
      description="The <html> element has no lang attribute.", remediation='Declare the language, e.g. <html lang="en">.')
def _lang(d: Dataset) -> list[FindingResult]:
    return _single("missing_lang", [_occ(p) for p in _html_pages(d) if not p.extracted.get("lang")], "page")


# ------------------------------------------------------------------ content


@rule(key="missing_h1", category="content", title="Missing H1 heading", severity="medium", kind="deterministic",
      description="The page has no H1 heading.", remediation="Add one H1 that states the page's main topic.")
def _missing_h1(d: Dataset) -> list[FindingResult]:
    return _single("missing_h1", [_occ(p, headings=p.extracted.get("headings", [])[:5]) for p in _html_pages(d, True) if not p.extracted.get("h1")], "page")


@rule(key="multiple_h1", category="content", title="Multiple H1 headings", severity="low", kind="heuristic",
      description="The page has more than one H1. This is valid HTML but often signals unclear structure.",
      remediation="Consider a single H1 with H2-H6 for subsections.")
def _multi_h1(d: Dataset) -> list[FindingResult]:
    return _single("multiple_h1", [_occ(p, h1=p.extracted.get("h1")) for p in _html_pages(d, True) if len(p.extracted.get("h1") or []) > 1], "page")


@rule(key="heading_skip", category="content", title="Heading levels skipped", severity="info", kind="heuristic",
      description="Heading levels jump (e.g. H2 to H4), which can hurt accessibility and document outline.",
      remediation="Use sequential heading levels.")
def _heading_skip(d: Dataset) -> list[FindingResult]:
    occ = []
    for p in _html_pages(d, True):
        levels = [h["level"] for h in p.extracted.get("headings", [])]
        for a, b in zip(levels, levels[1:], strict=False):
            if b - a > 1:
                occ.append(_occ(p, sequence=levels[:20]))
                break
    return _single("heading_skip", occ, "page")


@rule(key="thin_content", category="content", title="Possibly thin content", severity="low", kind="heuristic",
      description="Indexable page with fewer than 200 words of visible text. This is a heuristic, not a quality judgement.",
      remediation="Review whether the page satisfies its intent; expand, consolidate, or noindex if it adds little value.")
def _thin(d: Dataset) -> list[FindingResult]:
    return _single("thin_content", [_occ(p, word_count=p.extracted.get("word_count")) for p in _html_pages(d, True)
                                    if (p.extracted.get("word_count") or 0) < 200 and not p.extracted.get("needs_js_render")], "page")


@rule(key="js_rendering_required", category="crawlability", title="Content appears to require JavaScript rendering",
      severity="info", kind="heuristic",
      description="Very little server-rendered text plus app-shell markers. Analysis of these pages may be incomplete.",
      remediation="Prefer server-side rendering or pre-rendering for important content.")
def _js(d: Dataset) -> list[FindingResult]:
    return _single("js_rendering_required", [_occ(p, word_count=p.extracted.get("word_count")) for p in _html_pages(d) if p.extracted.get("needs_js_render")], "page")


# ------------------------------------------------------------------ indexability


@rule(key="http_4xx", category="indexability", title="Pages returning 4xx", severity="high", kind="deterministic",
      description="Crawled URLs return a client error.", remediation="Restore the page, redirect it to a relevant URL, or remove links to it.")
def _4xx(d: Dataset) -> list[FindingResult]:
    return _single("http_4xx", [_occ(p, status=p.status_code) for p in d.pages if 400 <= p.status_code < 500], "URL")


@rule(key="http_5xx", category="indexability", title="Pages returning 5xx", severity="critical", kind="deterministic",
      description="Crawled URLs return a server error.", remediation="Investigate server logs and fix the error.")
def _5xx(d: Dataset) -> list[FindingResult]:
    return _single("http_5xx", [_occ(p, status=p.status_code) for p in d.pages if p.status_code >= 500], "URL")


@rule(key="noindex_in_sitemap", category="indexability", title="Noindex pages listed in sitemap", severity="high", kind="deterministic",
      description="The sitemap lists URLs that tell search engines not to index them — contradictory signals.",
      remediation="Remove noindexed URLs from the sitemap, or remove noindex if the page should be indexed (requires review).")
def _noindex_sitemap(d: Dataset) -> list[FindingResult]:
    return _single("noindex_in_sitemap", [_occ(p, robots=p.robots_directives.strip(",")) for p in d.pages if p.in_sitemap and p.is_html_ok and p.noindex], "page")


@rule(key="sitemap_non_200", category="indexability", title="Sitemap URLs that redirect or error", severity="medium", kind="deterministic",
      description="Sitemaps should list only canonical, 200-status URLs.",
      remediation="Update the sitemap to list final, canonical URLs.")
def _sitemap_non200(d: Dataset) -> list[FindingResult]:
    return _single("sitemap_non_200", [_occ(p, status=p.status_code, final_url=p.final_url) for p in d.pages
                                       if p.in_sitemap and not p.blocked_by_robots and (p.status_code != 200 or p.redirect_chain)], "URL")


@rule(key="indexable_not_in_sitemap", category="indexability", title="Indexable pages missing from sitemap", severity="low",
      kind="heuristic", description="Indexable pages found by crawling that are not in any sitemap.",
      remediation="Add important indexable pages to the XML sitemap.")
def _not_in_sitemap(d: Dataset) -> list[FindingResult]:
    if not d.sitemap_urls:
        return []
    return _single("indexable_not_in_sitemap", [_occ(p) for p in _html_pages(d, True) if not p.in_sitemap and not p.redirect_chain], "page")


@rule(key="missing_sitemap", category="crawlability", title="No XML sitemap found", severity="low", kind="deterministic",
      description="No sitemap was found in robots.txt or at /sitemap.xml.", remediation="Publish an XML sitemap and reference it in robots.txt.")
def _no_sitemap(d: Dataset) -> list[FindingResult]:
    if d.sitemap_urls:
        return []
    return [FindingResult("missing_sitemap", RULES["missing_sitemap"].title, "No sitemap discovered.",
                          [Occurrence(url=f"https://{d.site_host}/sitemap.xml", evidence={"checked": d.sitemap_files or ["/sitemap.xml"]})])]


@rule(key="canonical_issues", category="indexability", title="Canonical tag problems", severity="medium", kind="deterministic",
      description="Multiple canonicals, canonical pointing to an error/redirect/noindex URL, or noindex combined with a cross-URL canonical.",
      remediation="Use a single absolute canonical pointing to an indexable 200 URL. Canonical changes require review.")
def _canonical(d: Dataset) -> list[FindingResult]:
    occ = []
    for p in _html_pages(d):
        ex = p.extracted
        canon = ex.get("canonical")
        problems = []
        if (ex.get("canonical_count") or 0) > 1:
            problems.append("multiple_canonicals")
        if canon and canon != p.url:
            target = d.by_url.get(canon)
            if target is not None:
                if target.status_code != 200:
                    problems.append(f"canonical_target_status_{target.status_code}")
                elif target.noindex:
                    problems.append("canonical_target_noindex")
                elif target.redirect_chain:
                    problems.append("canonical_target_redirects")
            if p.noindex:
                problems.append("noindex_with_cross_canonical")
            if p.in_sitemap:
                problems.append("sitemap_url_canonicalised_elsewhere")
        if problems:
            occ.append(_occ(p, canonical=canon, problems=problems))
    return _single("canonical_issues", occ, "page")


@rule(key="missing_canonical", category="indexability", title="Missing canonical tag", severity="info", kind="heuristic",
      description="No rel=canonical declared. Not an error, but explicit canonicals reduce duplicate-URL ambiguity.",
      remediation="Consider adding a self-referencing canonical.")
def _missing_canonical(d: Dataset) -> list[FindingResult]:
    return _single("missing_canonical", [_occ(p) for p in _html_pages(d, True) if not p.extracted.get("canonical")], "page")


# ------------------------------------------------------------------ links


@rule(key="broken_internal_links", category="links", title="Broken internal links", severity="high", kind="deterministic",
      description="Internal links point to URLs that return 4xx/5xx.",
      remediation="Update or remove the links (internal link edits require review).")
def _broken_links(d: Dataset) -> list[FindingResult]:
    occ = []
    for p in _html_pages(d):
        broken = []
        for link in p.extracted.get("links", []):
            t = d.by_url.get(link["href"])
            if t is not None and t.status_code >= 400:
                broken.append({"href": link["href"], "status": t.status_code, "anchor": link.get("text")})
        if broken:
            occ.append(_occ(p, broken_links=broken[:50], count=len(broken)))
    return _single("broken_internal_links", occ, "page")


@rule(key="redirect_chain", category="links", title="Redirect chains", severity="medium", kind="deterministic",
      description="URLs that take more than one redirect hop to resolve.", remediation="Redirect directly to the final URL (redirect changes require review).")
def _chains(d: Dataset) -> list[FindingResult]:
    return _single("redirect_chain", [_occ(p, chain=p.redirect_chain, final_url=p.final_url) for p in d.pages if len(p.redirect_chain) > 1], "URL")


@rule(key="internal_links_to_redirects", category="links", title="Internal links pointing to redirects", severity="low",
      kind="deterministic", description="Internal links that go through a redirect waste crawl and add latency.",
      remediation="Link directly to the final URL.")
def _links_to_redirects(d: Dataset) -> list[FindingResult]:
    occ = []
    for p in _html_pages(d):
        hits = [lk["href"] for lk in p.extracted.get("links", []) if (t := d.by_url.get(lk["href"])) is not None and t.redirect_chain]
        if hits:
            occ.append(_occ(p, links=hits[:20], count=len(hits)))
    return _single("internal_links_to_redirects", occ, "page")


# ------------------------------------------------------------------ structured data & media


@rule(key="invalid_structured_data", category="structured_data", title="Malformed structured data (JSON-LD)", severity="medium",
      kind="deterministic", description="JSON-LD blocks that fail to parse or lack @context/@type.",
      remediation="Fix the JSON-LD syntax and include @context and @type (structured data edits require review).")
def _jsonld(d: Dataset) -> list[FindingResult]:
    occ = []
    for p in _html_pages(d):
        problems = []
        for block in p.extracted.get("jsonld", []):
            if not block.get("valid_json"):
                problems.append({"error": block.get("error")})
                continue
            data = block.get("data")
            items = data if isinstance(data, list) else [data]
            for item in items:
                if isinstance(item, dict) and "@graph" not in item:
                    if "@context" not in item:
                        problems.append({"error": "missing @context"})
                    if "@type" not in item:
                        problems.append({"error": "missing @type"})
        if problems:
            occ.append(_occ(p, problems=problems[:10]))
    return _single("invalid_structured_data", occ, "page")


@rule(key="images_missing_alt", category="media", title="Images missing alt attribute", severity="low", kind="deterministic",
      description="Images without an alt attribute. (Decorative images should use alt=\"\").",
      remediation="Add descriptive alt text to meaningful images and empty alt to decorative ones.")
def _alt(d: Dataset) -> list[FindingResult]:
    occ = []
    for p in _html_pages(d):
        missing = [i.get("src") for i in p.extracted.get("images", []) if not i.get("has_alt_attr")]
        if missing:
            occ.append(_occ(p, images=missing[:20], count=len(missing)))
    return _single("images_missing_alt", occ, "page")


@rule(key="slow_server_response", category="performance", title="Slow server response observed by crawler", severity="low",
      kind="heuristic", description="HTML response took over 1.5s from our crawler. This is a single lab observation, not field (CrUX) data.",
      remediation="Check server/CDN caching. Confirm with PageSpeed Insights field data before acting.")
def _slow(d: Dataset) -> list[FindingResult]:
    return _single("slow_server_response", [_occ(p, response_ms=p.elapsed_ms) for p in _html_pages(d) if p.elapsed_ms > 1500], "page")


# ------------------------------------------------------------------ evaluation & scoring


def evaluate(dataset: Dataset) -> list[FindingResult]:
    results: list[FindingResult] = []
    for r in RULES.values():
        results.extend(r.check(dataset))
    return results


def health_score(dataset: Dataset, findings: list[FindingResult]) -> dict[str, Any]:
    total = max(1, len([p for p in dataset.pages if not p.blocked_by_robots]))
    by_rule: dict[str, set[str]] = defaultdict(set)
    for f in findings:
        by_rule[f.rule_key].update(o.url for o in f.occurrences)
    categories: dict[str, float] = defaultdict(lambda: 100.0)
    overall = 100.0
    penalties = []
    for key, urls in by_rule.items():
        r = RULES[key]
        coverage = min(1.0, math.sqrt(len(urls) / total))
        pts = SEVERITY_POINTS[r.severity] * r.weight * coverage * (HEURISTIC_FACTOR if r.kind == "heuristic" else 1.0)
        overall -= pts
        categories[r.category] -= pts * 2.5  # categories are narrower, so scale penalties up
        penalties.append({"rule": key, "points": round(pts, 2), "affected": len(urls)})
    for c in {r.category for r in RULES.values()}:
        categories[c] = round(max(0.0, min(100.0, categories[c])), 1)
    return {
        "score": round(max(0.0, min(100.0, overall)), 1),
        "categories": dict(categories),
        "penalties": sorted(penalties, key=lambda x: -x["points"]),
        "pages_evaluated": total,
        "label": "Internal diagnostic score — not a Google score",
        "methodology": SCORE_METHODOLOGY,
    }
