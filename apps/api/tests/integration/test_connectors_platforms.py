"""Shopify and GitHub connector behaviour against in-memory fakes of their APIs, plus
signature-verified, replay-protected platform webhooks."""

import asyncio
import base64
import hashlib
import hmac
import json
import re
import uuid

import httpx
import pytest

from aseo.connectors import github as gh_mod
from aseo.connectors import shopify as shop_mod
from aseo.connectors.base import ConnectorContext, StaleResourceError
from aseo.crawler.netguard import FetchResult

# ------------------------------------------------------------------ Shopify fake


class FakeShopify:
    def __init__(self):
        self.products = {"cold-brew-kit": {"id": "gid://shopify/Product/1", "updatedAt": "2026-10-01T00:00:00Z",
                                           "seo": {"title": "", "description": ""}}}
        self.pages = {"about": {"id": "gid://shopify/Page/7", "updatedAt": "2026-10-01T00:00:00Z", "t": None, "d": None}}
        self.calls = 0
        self.throttle = 0
        self.tick = 0

    def stamp(self):
        self.tick += 1
        return f"2026-10-02T00:00:{self.tick:02d}Z"

    async def fetch(self, url, method="GET", json_body=None, headers=None, **kw):
        assert url.startswith("https://demo-store.myshopify.com/admin/api/")
        assert headers["X-Shopify-Access-Token"] == "shpat_test"
        self.calls += 1
        if self.throttle:
            self.throttle -= 1
            return self._r({"errors": [{"message": "Throttled", "extensions": {"code": "THROTTLED"}}]})
        q, v = json_body["query"], json_body.get("variables", {})
        if "products(first" in q:
            h = v["q"].split(":", 1)[1]
            p = self.products.get(h)
            return self._r({"data": {"products": {"nodes": [{**p, "handle": h}] if p else []}}})
        if "pages(first" in q:
            h = v["q"].split(":", 1)[1]
            p = self.pages.get(h)
            node = {"id": p["id"], "handle": h, "updatedAt": p["updatedAt"], "t": {"value": p["t"]} if p["t"] else None,
                    "d": {"value": p["d"]} if p["d"] else None} if p else None
            return self._r({"data": {"pages": {"nodes": [node] if node else []}}})
        if "productUpdate" in q:
            prod = next(x for x in self.products.values() if x["id"] == v["p"]["id"])
            prod["seo"].update(v["p"]["seo"])
            prod["updatedAt"] = self.stamp()
            return self._r({"data": {"productUpdate": {"product": {"id": prod["id"], "updatedAt": prod["updatedAt"]}, "userErrors": []}}})
        if "metafieldsSet" in q:
            page = next(x for x in self.pages.values() if x["id"] == v["m"][0]["ownerId"])
            for m in v["m"]:
                page["d" if m["key"] == "description_tag" else "t"] = m["value"]
            page["updatedAt"] = self.stamp()
            return self._r({"data": {"metafieldsSet": {"metafields": [{"id": "gid://m/1", "updatedAt": page["updatedAt"]}], "userErrors": []}}})
        if "shop{" in q.replace(" ", ""):
            return self._r({"data": {"shop": {"name": "Demo", "myshopifyDomain": "demo-store.myshopify.com",
                                              "primaryDomain": {"host": "shop.example.com", "url": "https://shop.example.com"}}}})
        raise AssertionError(q)

    @staticmethod
    def _r(body):
        return FetchResult("u", "u", 200, {"content-type": "application/json"}, json.dumps(body).encode())


@pytest.fixture()
def shopify(monkeypatch):
    fake = FakeShopify()
    monkeypatch.setattr(shop_mod, "safe_fetch", fake.fetch)

    async def live(url):
        h = url.rstrip("/").split("/")[-1]
        if "/products/" in url:
            return {"meta_description": fake.products[h]["seo"]["description"], "title": "x", "status_code": 200}
        return {"meta_description": fake.pages[h]["d"], "title": "x", "status_code": 200}

    monkeypatch.setattr(shop_mod, "fetch_live_fields", live)
    ctx = ConnectorContext("s", "https://shop.example.com/", "shop.example.com", "c", "shopify", "live",
                           {"shop": "demo-store.myshopify.com"}, {"access_token": "shpat_test"})
    return fake, ctx


def run(c):
    return asyncio.run(c)


def test_shopify_product_write_verify_rollback(shopify):
    fake, ctx = shopify
    conn = shop_mod.ShopifyConnector()
    assert run(conn.verify_ownership(ctx))["domain_match"] is True
    url = "https://shop.example.com/products/cold-brew-kit"
    prep = run(conn.prepare_patch(ctx, url, "meta_description", {"meta_description": "Everything you need for smooth cold brew at home."}))
    patch = {"resource": prep.ref, "after": prep.after, "before": prep.before}
    res = run(conn.apply_patch(ctx, patch, expected_version=prep.resource_version, change_ref="lodestar:x"))
    assert res.applied and fake.products["cold-brew-kit"]["seo"]["description"].startswith("Everything")
    ver = run(conn.verify_patch(ctx, patch, {}))
    assert ver.verified
    rb = run(conn.rollback(ctx, patch, {"previous_value": {"meta_description": ""}}, current_version=None, change_ref="r"))
    assert rb.restored and fake.products["cold-brew-kit"]["seo"]["description"] == ""


def test_shopify_page_metafields_and_stale_and_throttle(shopify):
    fake, ctx = shopify
    conn = shop_mod.ShopifyConnector()
    url = "https://shop.example.com/pages/about"
    prep = run(conn.prepare_patch(ctx, url, "meta_description", {"meta_description": "Our story and the people behind the shop."}))
    patch = {"resource": prep.ref, "after": prep.after, "before": prep.before}
    fake.pages["about"]["updatedAt"] = "2026-10-05T00:00:00Z"  # someone edited
    with pytest.raises(StaleResourceError):
        run(conn.apply_patch(ctx, patch, expected_version=prep.resource_version, change_ref="x"))
    fake.throttle = 1
    from aseo.core.errors import ConnectorError

    with pytest.raises(ConnectorError) as e:
        run(conn.read_resource(ctx, url))
    assert e.value.retryable
    res = run(conn.apply_patch(ctx, patch, expected_version=None, change_ref="x"))
    assert res.applied and fake.pages["about"]["d"] == "Our story and the people behind the shop."
    # rollback refuses when a human changed the value after us
    fake.pages["about"]["d"] = "Human edit"
    rb = run(conn.rollback(ctx, patch, {"previous_value": {"meta_description": ""}}, current_version=None, change_ref="r"))
    assert not rb.restored and rb.requires_human


def test_shopify_rejects_unsupported_urls_and_bad_shop(shopify):
    _, ctx = shopify
    conn = shop_mod.ShopifyConnector()
    from aseo.core.errors import ConnectorError

    with pytest.raises(ConnectorError):
        run(conn.read_resource(ctx, "https://shop.example.com/cart"))
    bad = ConnectorContext("s", "", "", "c", "shopify", "live", {"shop": "evil.com"}, {"access_token": "t"})
    with pytest.raises(ConnectorError):
        run(conn.read_resource(bad, "https://shop.example.com/products/x"))


# ------------------------------------------------------------------ GitHub fake


class FakeGitHub:
    def __init__(self):
        self.files = {"main": {"content/about.md": "---\ntitle: About\n---\nHello\n"}}
        self.pulls = {}
        self.refs = {"main": "sha-main"}

    def handler(self, request: httpx.Request) -> httpx.Response:
        path, m = request.url.path, request.method
        if path.startswith("/app/installations/") and m == "POST":
            return httpx.Response(201, json={"token": "ghs_test"})
        assert request.headers["authorization"] == "token ghs_test"
        if path == "/repos/acme/site" and m == "GET":
            return httpx.Response(200, json={"full_name": "acme/site", "default_branch": "main", "homepage": "https://acme.example"})
        mm = re.match(r"/repos/acme/site/contents/(.+)", path)
        if mm and m == "GET":
            branch = request.url.params.get("ref")
            text = self.files.get(branch, {}).get(mm.group(1))
            if text is None:
                return httpx.Response(404, json={"message": "Not Found"})
            return httpx.Response(200, json={"content": base64.b64encode(text.encode()).decode(), "sha": hashlib.sha1(text.encode()).hexdigest()})
        if path == "/repos/acme/site/git/ref/heads/main":
            return httpx.Response(200, json={"object": {"sha": self.refs["main"]}})
        if path == "/repos/acme/site/git/refs" and m == "POST":
            ref = json.loads(request.content)["ref"].split("refs/heads/")[1]
            assert ref != "main"
            self.files[ref] = dict(self.files["main"])
            return httpx.Response(201, json={})
        if mm and m == "PUT":
            body = json.loads(request.content)
            assert body["branch"] != "main", "must never write to the default branch"
            self.files[body["branch"]][mm.group(1)] = base64.b64decode(body["content"]).decode()
            return httpx.Response(200, json={})
        if path == "/repos/acme/site/pulls" and m == "POST":
            body = json.loads(request.content)
            n = len(self.pulls) + 1
            self.pulls[n] = {"number": n, "state": "open", "merged": False, "head": body["head"], "html_url": f"https://github.com/acme/site/pull/{n}"}
            return httpx.Response(201, json=self.pulls[n])
        pm = re.match(r"/repos/acme/site/pulls/(\d+)", path)
        if pm:
            pr = self.pulls[int(pm.group(1))]
            if m == "PATCH":
                pr.update(json.loads(request.content))
            return httpx.Response(200, json=pr)
        raise AssertionError(f"{m} {path}")


@pytest.fixture()
def github(monkeypatch):
    fake = FakeGitHub()
    monkeypatch.setattr(gh_mod, "app_jwt", lambda: "jwt")
    live_value = {"v": "About"}

    async def live(url):
        return {"meta_description": live_value["v"], "title": "About", "status_code": 200, "fetched_url": url}

    monkeypatch.setattr(gh_mod, "fetch_live_fields", live)
    client = httpx.AsyncClient(transport=httpx.MockTransport(fake.handler))
    conn = gh_mod.GitHubConnector(client=client)
    ctx = ConnectorContext("s", "https://acme.example/", "acme.example", "c", "github", "live",
                           {"owner": "acme", "repo": "site", "base_branch": "main", "installation_id": "42", "framework": "markdown-frontmatter"})
    return fake, conn, ctx, live_value


def test_github_opens_pr_never_pushes_default_branch(github):
    fake, conn, ctx, live = github
    url = "https://acme.example/about"
    prep = run(conn.prepare_patch(ctx, url, "meta_description", {"meta_description": "Who we are and what we build at Acme."}))
    assert prep.before == {"meta_description": ""}
    patch = {"resource": prep.ref, "after": prep.after, "before": prep.before}
    res = run(conn.apply_patch(ctx, patch, expected_version=prep.resource_version, change_ref="lodestar:abc:v1"))
    assert res.live is False and res.external_url.endswith("/pull/1")
    assert "description" not in fake.files["main"]["content/about.md"]
    branch = fake.pulls[1]["head"]
    assert 'description: "Who we are and what we build at Acme."' in fake.files[branch]["content/about.md"]
    # not merged -> pending (awaiting deploy), never reported as verified
    v = run(conn.verify_patch(ctx, patch, {"response": res.response, "external_url": res.external_url}))
    assert not v.verified and v.pending
    # merged + deployed -> verified from live HTML
    fake.pulls[1]["merged"] = True
    live["v"] = "Who we are and what we build at Acme."
    v = run(conn.verify_patch(ctx, patch, {"response": res.response}))
    assert v.verified
    # rollback of an unmerged PR closes it
    fake.pulls[1]["merged"] = False
    rb = run(conn.rollback(ctx, patch, {"previous_value": {"meta_description": ""}, "apply": {"response": res.response}}, current_version=None,
                           change_ref="r"))
    assert rb.restored and fake.pulls[1]["state"] == "closed"


def test_github_static_html_transform():
    html = "<html><head><title>Old</title></head><body></body></html>"
    out = gh_mod.GitHubConnector.transform("static-html", html, "meta_description", 'Fresh "quoted" text')
    assert '<meta name="description" content="Fresh &quot;quoted&quot; text">' in out
    assert gh_mod.GitHubConnector.extract("static-html", out)["meta_description"] == 'Fresh "quoted" text'


# ------------------------------------------------------------------ platform webhooks


def test_github_webhook_signature_and_replay(client, monkeypatch):
    from aseo.core.config import get_settings

    monkeypatch.setattr(get_settings(), "github_webhook_secret", "gh-secret")
    body = json.dumps({"action": "closed", "repository": {"full_name": "acme/site"}, "pull_request": {"merged": True}}).encode()
    sig = "sha256=" + hmac.new(b"gh-secret", body, hashlib.sha256).hexdigest()
    delivery = str(uuid.uuid4())
    h = {"x-github-event": "pull_request", "x-github-delivery": delivery, "content-type": "application/json"}
    assert client.post("/api/v1/webhooks/github", content=body, headers={**h, "x-hub-signature-256": "sha256=bad"}).status_code == 401
    assert client.post("/api/v1/webhooks/github", content=body, headers={**h, "x-hub-signature-256": sig}).status_code == 200
    assert client.post("/api/v1/webhooks/github", content=body, headers={**h, "x-hub-signature-256": sig}).status_code == 409


def test_shopify_webhook_signature(client, monkeypatch):
    from aseo.core.config import get_settings

    monkeypatch.setattr(get_settings(), "shopify_api_secret", "shp-secret")
    body = b'{"id": 1}'
    sig = base64.b64encode(hmac.new(b"shp-secret", body, hashlib.sha256).digest()).decode()
    h = {"x-shopify-topic": "products/update", "x-shopify-shop-domain": "unknown.myshopify.com", "x-shopify-webhook-id": str(uuid.uuid4())}
    assert client.post("/api/v1/webhooks/shopify", content=body, headers={**h, "x-shopify-hmac-sha256": "bad"}).status_code == 401
    assert client.post("/api/v1/webhooks/shopify", content=body, headers={**h, "x-shopify-hmac-sha256": sig}).status_code == 200


def test_gsc_demo_sync_is_labelled(wp_site):
    from tests.conftest import drain

    api, site = wp_site
    r = api.post(f"/integrations/gsc/authorize?site_id={site['id']}")
    assert r.json()["mode"] == "fixture"
    drain()
    perf = api.get(f"/sites/{site['id']}/performance?days=90").json()
    assert perf["is_demo_data"] is True and perf["source"] == "demo_fixture" and perf["series"]
    kw = api.get(f"/sites/{site['id']}/keywords").json()
    assert kw["queries"] and all(q["source"] == "demo_fixture" and q["search_volume"] is None for q in kw["queries"])
