"""In-memory fixture website for crawler/rule tests."""

from aseo.crawler.netguard import FetchResult

BASE = "https://fixture.test/"


def page(title, desc=None, body="", extra_head="", canonical=None, lang="en"):
    head = f"<title>{title}</title>" if title else ""
    if desc is not None:
        head += f'<meta name="description" content="{desc}">'
    if canonical:
        head += f'<link rel="canonical" href="{canonical}">'
    head += '<meta name="viewport" content="width=device-width">' + extra_head
    words = " ".join(["word"] * 250)
    return f'<html lang="{lang}"><head>{head}</head><body>{body}<p>{words}</p></body></html>'


PAGES = {
    "https://fixture.test/robots.txt": (200, "text/plain", "User-agent: *\nDisallow: /private/\nSitemap: https://fixture.test/sitemap.xml\n"),
    "https://fixture.test/sitemap.xml": (200, "application/xml",
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        "<url><loc>https://fixture.test/</loc></url><url><loc>https://fixture.test/about</loc></url>"
        "<url><loc>https://fixture.test/hidden</loc></url><url><loc>https://fixture.test/old</loc></url></urlset>"),
    "https://fixture.test/": (200, "text/html", page("Fixture Home — a well described homepage", "A good description of the fixture homepage that has a sensible length for snippets.",
        '<h1>Home</h1><a href="/about">About</a><a href="/blog/post">Post</a><a href="/missing">Broken</a><a href="/private/x">P</a><a href="/old">Old</a><img src="/a.png">')),
    "https://fixture.test/about": (200, "text/html", page("About", None, "<h1>About us</h1>")),
    "https://fixture.test/blog/post": (200, "text/html", page("About", "", "<h1>Post</h1><h1>Second</h1>",
        extra_head='<script type="application/ld+json">{"name": "no type"}</script>')),
    "https://fixture.test/hidden": (200, "text/html", page("Hidden page title for testing", "Hidden description long enough to be in range for the heuristic length rule ok.", "<h1>H</h1>",
        extra_head='<meta name="robots" content="noindex">')),
    "https://fixture.test/missing": (404, "text/html", "<html><body>nope</body></html>"),
}
REDIRECTS = {"https://fixture.test/old": "https://fixture.test/about"}


async def fixture_fetch(url: str) -> FetchResult:
    if url in REDIRECTS:
        return FetchResult(url, REDIRECTS[url], 200, {"content-type": "text/html"}, PAGES[REDIRECTS[url]][2].encode(),
                           redirect_chain=[{"url": url, "status": 301, "location": REDIRECTS[url]}], elapsed_ms=5)
    if url not in PAGES:
        return FetchResult(url, url, 404, {"content-type": "text/html"}, b"not found", elapsed_ms=3)
    status, ctype, body = PAGES[url]
    return FetchResult(url, url, status, {"content-type": ctype}, body.encode(), elapsed_ms=10)
