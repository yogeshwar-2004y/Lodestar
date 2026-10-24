"""Polite, bounded, scope-aware crawler (no database access — pure data in/out)."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from aseo.core.security import sha256_hex
from aseo.crawler.netguard import BlockedDestination, FetchResult, safe_fetch
from aseo.crawler.parse import extract_html, parse_sitemap
from aseo.crawler.robots import Robots, parse_robots
from aseo.crawler.urls import InvalidURL, in_path_scope, is_probably_html_url, normalize_url, same_site

Fetcher = Callable[[str], Awaitable[FetchResult]]


@dataclass
class CrawlConfig:
    base_url: str
    site_host: str
    max_pages: int = 200
    max_depth: int = 6
    include_paths: list[str] = field(default_factory=list)
    exclude_paths: list[str] = field(default_factory=list)
    respect_robots: bool = True
    user_agent: str = "LodestarBot/1.0"
    concurrency: int = 2
    delay_seconds: float = 0.25
    max_sitemaps: int = 20
    time_budget_seconds: float = 600


@dataclass
class PageResult:
    url: str
    depth: int
    status_code: int
    final_url: str
    headers: dict[str, str]
    redirect_chain: list[dict[str, Any]]
    elapsed_ms: int
    content_hash: str | None
    html: str | None
    extracted: dict[str, Any]
    in_sitemap: bool
    error: str | None = None
    blocked_by_robots: bool = False


@dataclass
class CrawlOutput:
    pages: list[PageResult]
    robots_txt: str | None
    robots: Robots | None
    sitemap_urls: list[str]
    sitemap_page_urls: set[str]
    stats: dict[str, Any]


async def _default_fetch(url: str) -> FetchResult:
    return await safe_fetch(url)


async def _load_robots(cfg: CrawlConfig, fetch: Fetcher) -> tuple[Robots | None, str | None]:
    url = normalize_url("/robots.txt", cfg.base_url)
    try:
        res = await fetch(url)
    except (BlockedDestination, Exception):  # noqa: BLE001
        return None, None
    if res.status_code == 200:
        return parse_robots(res.text), res.text
    if 500 <= res.status_code < 600:
        r = Robots(disallow_all=True)
        return r, None
    return Robots(), None  # 4xx => no restrictions


async def _load_sitemaps(cfg: CrawlConfig, robots: Robots | None, fetch: Fetcher) -> tuple[list[str], set[str]]:
    queue = list(robots.sitemaps if robots else [])
    if not queue:
        queue.append(normalize_url("/sitemap.xml", cfg.base_url))
    seen: list[str] = []
    pages: set[str] = set()
    while queue and len(seen) < cfg.max_sitemaps:
        sm = queue.pop(0)
        try:
            sm_norm = normalize_url(sm, cfg.base_url)
        except InvalidURL:
            continue
        if sm_norm in seen or not same_site(sm_norm, cfg.site_host):
            continue
        seen.append(sm_norm)
        try:
            res = await fetch(sm_norm)
        except Exception:  # noqa: BLE001
            continue
        if res.status_code != 200:
            continue
        urls, children = parse_sitemap(res.body)
        for u in urls:
            try:
                pages.add(normalize_url(u))
            except InvalidURL:
                continue
        queue.extend(children)
    return seen, pages


async def crawl(cfg: CrawlConfig, fetch: Fetcher | None = None, on_progress: Callable[[int], None] | None = None) -> CrawlOutput:
    fetch = fetch or _default_fetch
    started = time.monotonic()
    robots, robots_txt = await _load_robots(cfg, fetch)
    sitemap_files, sitemap_pages = await _load_sitemaps(cfg, robots, fetch)
    delay = cfg.delay_seconds
    if robots and cfg.respect_robots:
        cd = robots.crawl_delay(cfg.user_agent)
        if cd:
            delay = max(delay, cd)

    start = normalize_url(cfg.base_url)
    frontier: list[tuple[str, int]] = [(start, 0)]
    for u in sorted(sitemap_pages):
        frontier.append((u, 1))
    seen: set[str] = set()
    results: list[PageResult] = []
    stats = {"blocked_by_robots": 0, "out_of_scope": 0, "errors": 0, "skipped_non_html": 0, "truncated": 0}
    sem = asyncio.Semaphore(max(1, cfg.concurrency))
    last_request = [0.0]
    lock = asyncio.Lock()

    async def polite_fetch(url: str) -> FetchResult:
        async with sem:
            async with lock:
                wait = last_request[0] + delay - time.monotonic()
                if wait > 0:
                    await asyncio.sleep(wait)
                last_request[0] = time.monotonic()
            return await fetch(url)

    async def process(url: str, depth: int) -> PageResult | None:
        if cfg.respect_robots and robots and not robots.allowed(url, cfg.user_agent):
            stats["blocked_by_robots"] += 1
            return PageResult(url, depth, 0, url, {}, [], 0, None, None, {}, url in sitemap_pages, None, True)
        try:
            res = await polite_fetch(url)
        except BlockedDestination as exc:
            stats["errors"] += 1
            return PageResult(url, depth, 0, url, {}, [], 0, None, None, {}, url in sitemap_pages, f"blocked: {exc}")
        except Exception as exc:  # noqa: BLE001 - network errors become page errors
            stats["errors"] += 1
            return PageResult(url, depth, 0, url, {}, [], 0, None, None, {}, url in sitemap_pages, f"{type(exc).__name__}: {exc}"[:300])
        ctype = res.headers.get("content-type", "")
        html = None
        extracted: dict[str, Any] = {}
        chash = None
        if res.truncated:
            stats["truncated"] += 1
        if res.redirect_chain:
            # Record the source as a redirect; the destination is crawled as its own page.
            return PageResult(
                url=url, depth=depth, status_code=int(res.redirect_chain[0]["status"]), final_url=res.final_url,
                headers={"location": str(res.redirect_chain[0]["location"])}, redirect_chain=res.redirect_chain,
                elapsed_ms=res.elapsed_ms, content_hash=None, html=None, extracted={}, in_sitemap=url in sitemap_pages,
                error=res.error,
            )
        if res.status_code == 200 and ("html" in ctype or not ctype):
            html = res.text
            chash = sha256_hex(res.body)
            extracted = extract_html(html, res.final_url)
        return PageResult(
            url=url,
            depth=depth,
            status_code=res.status_code,
            final_url=res.final_url,
            headers={k: v for k, v in res.headers.items() if k in ("content-type", "x-robots-tag", "last-modified", "etag", "cache-control", "content-length", "location")},
            redirect_chain=res.redirect_chain,
            elapsed_ms=res.elapsed_ms,
            content_hash=chash,
            html=html,
            extracted=extracted,
            in_sitemap=url in sitemap_pages,
            error=res.error,
        )

    while frontier and len(results) < cfg.max_pages:
        if time.monotonic() - started > cfg.time_budget_seconds:
            stats["time_budget_exhausted"] = True
            break
        batch: list[tuple[str, int]] = []
        while frontier and len(batch) + len(results) < cfg.max_pages and len(batch) < cfg.concurrency * 4:
            url, depth = frontier.pop(0)
            if url in seen:
                continue
            seen.add(url)
            if not same_site(url, cfg.site_host) or not in_path_scope(url, cfg.include_paths, cfg.exclude_paths):
                stats["out_of_scope"] += 1
                continue
            if not is_probably_html_url(url):
                stats["skipped_non_html"] += 1
                continue
            batch.append((url, depth))
        if not batch:
            continue
        page_results = await asyncio.gather(*(process(u, d) for u, d in batch))
        for pr in page_results:
            if pr is None:
                continue
            results.append(pr)
            if on_progress:
                on_progress(len(results))
            # follow redirect target and links
            if pr.redirect_chain and pr.final_url != pr.url:
                try:
                    frontier.append((normalize_url(pr.final_url), pr.depth))
                except InvalidURL:
                    pass
            if pr.depth < cfg.max_depth:
                for link in pr.extracted.get("links", []):
                    href = link["href"]
                    if href not in seen and same_site(href, cfg.site_host):
                        frontier.append((href, pr.depth + 1))

    stats["pages"] = len(results)
    stats["duration_ms"] = int((time.monotonic() - started) * 1000)
    stats["sitemap_urls"] = len(sitemap_pages)
    stats["crawl_delay_seconds"] = delay
    return CrawlOutput(results, robots_txt, robots, sitemap_files, sitemap_pages, stats)
