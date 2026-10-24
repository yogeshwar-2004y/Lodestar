"""WordPress TEST FIXTURE — not a real WordPress install.

Implements the Lodestar Companion plugin REST contract (lodestar/v1/*) plus public HTML
pages, robots.txt and sitemap.xml so the full M1 loop (crawl -> detect -> write -> live
verification -> rollback) can run locally and in CI without a WordPress site. Writes made
by Lodestar against this fixture are real HTTP writes to this fixture only, and the UI
labels such connectors as "Fixture".

Run:  python integrations/wordpress/fixture_server/server.py  (port 8481)

Fixture-only control endpoints (no auth, bind to localhost only):
  POST /__fixture/settings {"verification_token": "..."}
  POST /__fixture/faults   {"status": 429|500, "count": 2, "delay": 0}
  POST /__fixture/edit     {"id": 4, "description": "..."}   # simulate a human edit (stale version)
  POST /__fixture/reset
  POST /__fixture/cache    {"seconds": 0}                     # simulate a page cache
"""

from __future__ import annotations

import base64
import hashlib
import html
import json
import os
import threading
import time
import uuid
from copy import deepcopy
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, Response

USERNAME = os.environ.get("WP_FIXTURE_USER", "lodestar-agent")
APP_PASSWORD = os.environ.get("WP_FIXTURE_APP_PASSWORD", "fixture-app-password")

SEED_POSTS: list[dict[str, Any]] = [
    {"id": 1, "type": "page", "slug": "", "title": "Northwind Coffee Roasters",
     "seo": {"title": "", "description": "Small-batch coffee roasted weekly in Portland. Shop single-origin beans, brewing gear and subscriptions."},
     "body": "<h1>Northwind Coffee Roasters</h1><p>Freshly roasted coffee delivered to your door.</p>"
             '<a href="/about/">About</a> <a href="/subscriptions/">Subscriptions</a> <a href="/brew-guides/pour-over/">Pour-over guide</a> '
             '<a href="/contact/">Contact</a> <a href="/wholesale/">Wholesale</a> <img src="/wp-content/beans.jpg">'},
    {"id": 2, "type": "page", "slug": "about", "title": "About us",
     "seo": {"title": "About Northwind Coffee Roasters", "description": "Meet the team behind Northwind: roasting ethically sourced coffee in Portland since 2014."},
     "body": "<h1>About Northwind</h1><p>We started roasting in a garage in 2014.</p><a href=\"/\">Home</a>"},
    {"id": 3, "type": "page", "slug": "subscriptions", "title": "Coffee subscriptions",
     "seo": {"title": "", "description": ""},
     "body": "<h1>Coffee subscriptions</h1><p>Choose a roast, pick a schedule, pause anytime. Subscriptions ship every two or four weeks "
             "with beans roasted within 48 hours of shipping.</p><a href=\"/\">Home</a>"},
    {"id": 4, "type": "post", "slug": "brew-guides/pour-over", "title": "How to brew pour-over coffee",
     "seo": {"title": "", "description": ""},
     "body": "<h1>How to brew pour-over coffee</h1><h3>What you need</h3><p>A dripper, filter, scale and kettle. Use a 1:16 ratio, "
             "bloom for 30 seconds, then pour in slow spirals.</p><a href=\"/\">Home</a> <a href=\"/old-guide/\">Old guide</a>"},
    {"id": 5, "type": "page", "slug": "contact", "title": "Contact",
     "seo": {"title": "", "description": "Contact"},
     "body": "<h1>Contact</h1><p>hello@northwind.example</p>"},
]

LOCK = threading.Lock()
STATE: dict[str, Any] = {}


def reset() -> None:
    with LOCK:
        STATE.clear()
        STATE.update({"posts": {p["id"]: deepcopy(p) for p in SEED_POSTS}, "token": os.environ.get("WP_FIXTURE_VERIFY_TOKEN", ""),
                      "faults": {"status": None, "count": 0, "delay": 0.0}, "history": {}, "cache_seconds": 0, "cache": {}})


reset()
app = FastAPI(title="WordPress fixture (Lodestar companion contract)")


def version(seo: dict[str, str]) -> str:
    return hashlib.sha1(json.dumps([seo["title"], seo["description"]]).encode()).hexdigest()[:16]


def permalink(request: Request, post: dict[str, Any]) -> str:
    base = str(request.base_url).rstrip("/")
    return f"{base}/{post['slug']}/" if post["slug"] else f"{base}/"


def payload(request: Request, post: dict[str, Any]) -> dict[str, Any]:
    return {"id": post["id"], "type": post["type"], "status": "publish", "permalink": permalink(request, post),
            "seo_plugin": "none", "writable": True, "seo": dict(post["seo"]), "version": version(post["seo"])}


def authorized(request: Request) -> bool:
    header = request.headers.get("authorization", "")
    if not header.startswith("Basic "):
        return False
    try:
        user, _, pw = base64.b64decode(header[6:]).decode().partition(":")
    except Exception:  # noqa: BLE001
        return False
    return user == USERNAME and pw == APP_PASSWORD


def maybe_fault() -> Response | None:
    f = STATE["faults"]
    if f["delay"]:
        time.sleep(f["delay"])
    if f["count"] > 0 and f["status"]:
        f["count"] -= 1
        return JSONResponse({"code": "fixture_fault", "message": "injected fault"}, status_code=f["status"])
    return None


def denied() -> JSONResponse:
    return JSONResponse({"code": "rest_forbidden", "message": "Sorry, you are not allowed to do that."}, status_code=401)


# ------------------------------------------------------------------ plugin REST contract


@app.get("/wp-json/lodestar/v1/status")
def status(request: Request):
    if not authorized(request):
        return denied()
    return {"plugin_version": "1.0.0-fixture", "seo_plugin": "none", "writable": True, "site_url": str(request.base_url),
            "verification_token": STATE["token"], "fixture": True}


@app.get("/wp-json/lodestar/v1/resolve")
def resolve(request: Request, url: str):
    if not authorized(request):
        return denied()
    if (fault := maybe_fault()) is not None:
        return fault
    path = "/" + url.split("://", 1)[-1].split("/", 1)[-1].split("?")[0]
    slug = path.strip("/")
    for post in STATE["posts"].values():
        if post["slug"] == slug:
            return payload(request, post)
    return JSONResponse({"code": "lodestar_not_found", "message": "No editable post"}, status_code=404)


@app.get("/wp-json/lodestar/v1/resources")
def resources(request: Request):
    if not authorized(request):
        return denied()
    return {"resources": [payload(request, p) for p in STATE["posts"].values()], "total": len(STATE["posts"])}


@app.get("/wp-json/lodestar/v1/seo/{post_id}")
def get_seo(request: Request, post_id: int):
    if not authorized(request):
        return denied()
    post = STATE["posts"].get(post_id)
    return payload(request, post) if post else JSONResponse({"code": "lodestar_not_found"}, status_code=404)


@app.post("/wp-json/lodestar/v1/seo/{post_id}")
async def write_seo(request: Request, post_id: int):
    if not authorized(request):
        return denied()
    if (fault := maybe_fault()) is not None:
        return fault
    body = await request.json()
    with LOCK:
        post = STATE["posts"].get(post_id)
        if not post:
            return JSONResponse({"code": "lodestar_not_found"}, status_code=404)
        fields = {k: v for k, v in (body.get("fields") or {}).items() if k in ("title", "description")}
        if not fields or any(not isinstance(v, str) or len(v) > 400 for v in fields.values()):
            return JSONResponse({"code": "lodestar_invalid", "message": "invalid fields"}, status_code=400)
        current = dict(post["seo"])
        cur_version = version(current)
        if body.get("expected_version") and body["expected_version"] != cur_version:
            return JSONResponse({"code": "lodestar_conflict", "message": "SEO fields changed", "data": {"status": 409},
                                 "current_version": cur_version}, status_code=409)
        post["seo"].update({k: " ".join(v.split()) for k, v in fields.items()})
        rev = str(uuid.uuid4())
        STATE["history"].setdefault(post_id, []).append({"revision_id": rev, "at": time.time(), "change_ref": body.get("change_ref"),
                                                         "is_rollback": bool(body.get("is_rollback")), "before": current, "after": dict(post["seo"])})
        STATE["cache"].pop(post_id, None) if STATE["cache_seconds"] == 0 else None
        return {"id": post_id, "revision_id": rev, "previous": current, "seo": dict(post["seo"]), "version": version(post["seo"])}


@app.get("/wp-json/lodestar/v1/seo/{post_id}/history")
def history(request: Request, post_id: int):
    if not authorized(request):
        return denied()
    return {"history": STATE["history"].get(post_id, [])}


# ------------------------------------------------------------------ fixture control


@app.post("/__fixture/settings")
async def fixture_settings(request: Request):
    body = await request.json()
    STATE["token"] = str(body.get("verification_token", ""))
    return {"ok": True}


@app.post("/__fixture/faults")
async def fixture_faults(request: Request):
    body = await request.json()
    STATE["faults"] = {"status": body.get("status"), "count": int(body.get("count", 0)), "delay": float(body.get("delay", 0))}
    return {"ok": True}


@app.post("/__fixture/edit")
async def fixture_edit(request: Request):
    body = await request.json()
    post = STATE["posts"][int(body["id"])]
    if "description" in body:
        post["seo"]["description"] = body["description"]
    if "title" in body:
        post["seo"]["title"] = body["title"]
    return {"ok": True, "version": version(post["seo"])}


@app.post("/__fixture/cache")
async def fixture_cache(request: Request):
    body = await request.json()
    STATE["cache_seconds"] = int(body.get("seconds", 0))
    STATE["cache"].clear()
    return {"ok": True}


@app.post("/__fixture/reset")
def fixture_reset():
    reset()
    return {"ok": True}


@app.get("/__fixture/state")
def fixture_state():
    return {"posts": STATE["posts"], "history": STATE["history"], "token_set": bool(STATE["token"])}


# ------------------------------------------------------------------ public site


@app.get("/robots.txt", response_class=PlainTextResponse)
def robots(request: Request):
    return f"User-agent: *\nDisallow: /wp-admin/\nAllow: /wp-admin/admin-ajax.php\n\nSitemap: {str(request.base_url).rstrip('/')}/sitemap.xml\n"


@app.get("/sitemap.xml")
def sitemap(request: Request):
    urls = "".join(f"<url><loc>{html.escape(permalink(request, p))}</loc></url>" for p in STATE["posts"].values())
    xml = f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>'
    return Response(xml, media_type="application/xml")


@app.get("/old-guide/")
def old_guide():
    return Response(status_code=301, headers={"Location": "/brew-guides/pour-over/"})


def render(request: Request, post: dict[str, Any]) -> str:
    seo = post["seo"]
    title = seo["title"] or f"{post['title']} – Northwind Coffee"
    desc = f'<meta name="description" content="{html.escape(seo["description"], quote=True)}" />' if seo["description"] else ""
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
            f"<title>{html.escape(title)}</title>{desc}"
            f'<link rel="canonical" href="{html.escape(permalink(request, post))}" />'
            f'<meta name="generator" content="WordPress fixture (Lodestar test)" /></head>'
            f"<body><!-- Lodestar WordPress TEST FIXTURE -->{post['body']}</body></html>")


@app.get("/{path:path}", response_class=HTMLResponse)
def page(request: Request, path: str):
    slug = path.strip("/")
    for post in STATE["posts"].values():
        if post["slug"] == slug:
            cached = STATE["cache"].get(post["id"])
            if STATE["cache_seconds"] and cached and cached[0] > time.time():
                return HTMLResponse(cached[1], headers={"x-cache": "HIT", "age": "1"})
            body = render(request, post)
            if STATE["cache_seconds"]:
                STATE["cache"][post["id"]] = (time.time() + STATE["cache_seconds"], body)
            return HTMLResponse(body, headers={"x-cache": "MISS"})
    return HTMLResponse("<html><head><title>Not found</title></head><body><h1>404</h1></body></html>", status_code=404)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("WP_FIXTURE_PORT", "8481")), log_level="warning")
