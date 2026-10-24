import asyncio

from aseo.crawler.engine import CrawlConfig, crawl
from aseo.rules.engine import RULES, Dataset, PageData, evaluate, health_score

from .fixture_site import BASE, fixture_fetch


def run_crawl(**kw):
    cfg = CrawlConfig(base_url=BASE, site_host="fixture.test", delay_seconds=0, **kw)
    return asyncio.run(crawl(cfg, fetch=fixture_fetch))


def to_dataset(out):
    pages = [PageData(p.url, p.status_code, p.final_url, p.depth, p.in_sitemap, p.redirect_chain, p.extracted, p.headers,
                      p.elapsed_ms, blocked_by_robots=p.blocked_by_robots) for p in out.pages]
    return Dataset("fixture.test", pages, out.sitemap_page_urls, out.sitemap_urls, out.robots is not None)


def test_crawl_respects_robots_scope_and_caps():
    out = run_crawl()
    urls = {p.url for p in out.pages}
    assert "https://fixture.test/about" in urls
    assert "https://fixture.test/missing" in urls
    blocked = [p for p in out.pages if p.blocked_by_robots]
    assert [p.url for p in blocked] == ["https://fixture.test/private/x"]
    assert out.stats["blocked_by_robots"] == 1
    assert "https://fixture.test/" in out.sitemap_page_urls
    capped = run_crawl(max_pages=2)
    assert len(capped.pages) == 2
    scoped = run_crawl(include_paths=["/blog"])
    assert {p.url for p in scoped.pages} <= {"https://fixture.test/blog/post"}


def test_rules_detect_expected_issues():
    ds = to_dataset(run_crawl())
    findings = evaluate(ds)
    by_rule = {}
    for f in findings:
        by_rule.setdefault(f.rule_key, []).append(f)
    missing_desc_urls = {o.url for f in by_rule["missing_meta_description"] for o in f.occurrences}
    assert missing_desc_urls == {"https://fixture.test/about", "https://fixture.test/blog/post"}
    assert {o.url for o in by_rule["http_4xx"][0].occurrences} == {"https://fixture.test/missing"}
    assert {o.url for o in by_rule["noindex_in_sitemap"][0].occurrences} == {"https://fixture.test/hidden"}
    assert by_rule["broken_internal_links"][0].occurrences[0].url == "https://fixture.test/"
    assert "duplicate_title" in by_rule  # "About" used twice
    assert "multiple_h1" in by_rule
    assert "invalid_structured_data" in by_rule
    assert "images_missing_alt" in by_rule
    assert "sitemap_non_200" in by_rule  # /old redirects
    # deterministic vs heuristic separation
    assert RULES["thin_content"].kind == "heuristic"
    assert RULES["missing_meta_description"].kind == "deterministic"


def test_fingerprints_stable_and_score_labelled():
    ds = to_dataset(run_crawl())
    f1 = sorted(f.fingerprint() for f in evaluate(ds))
    f2 = sorted(f.fingerprint() for f in evaluate(ds))
    assert f1 == f2
    hs = health_score(ds, evaluate(ds))
    assert 0 <= hs["score"] < 100
    assert "not a Google score" in hs["label"]


def test_perfect_site_scores_100():
    ex = {"title": "A perfectly fine page title here ok", "meta_description": "x" * 100, "viewport": "w", "lang": "en",
          "h1": ["H"], "headings": [{"level": 1, "text": "H"}], "links": [], "images": [], "jsonld": [], "word_count": 500,
          "canonical": "https://p.test/"}
    p = PageData("https://p.test/", 200, "https://p.test/", 0, True, [], ex, {}, 100)
    ds = Dataset("p.test", [p], {"https://p.test/"}, ["https://p.test/sitemap.xml"], True)
    assert evaluate(ds) == []
    assert health_score(ds, [])["score"] == 100
