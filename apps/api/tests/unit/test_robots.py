from aseo.crawler.robots import parse_robots

ROBOTS = """
User-agent: *
Disallow: /private/
Allow: /private/public-page
Disallow: /*.pdf$
Crawl-delay: 2

User-agent: LodestarBot
Disallow: /no-lodestar/

Sitemap: https://a.com/sitemap_index.xml
"""


def test_groups_and_precedence():
    r = parse_robots(ROBOTS)
    assert r.sitemaps == ["https://a.com/sitemap_index.xml"]
    star = "SomeBot/1.0"
    assert not r.allowed("https://a.com/private/x", star)
    assert r.allowed("https://a.com/private/public-page", star)
    assert not r.allowed("https://a.com/files/doc.pdf", star)
    assert r.allowed("https://a.com/files/doc.pdf?x=1", star)
    assert r.crawl_delay(star) == 2
    # specific group overrides *
    assert r.allowed("https://a.com/private/x", "LodestarBot/1.0")
    assert not r.allowed("https://a.com/no-lodestar/", "LodestarBot/1.0")


def test_disallow_all_flag():
    r = parse_robots("")
    r.disallow_all = True
    assert not r.allowed("https://a.com/", "x")
