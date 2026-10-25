from __future__ import annotations

import base64
import hashlib
import hmac
import json
import uuid
from datetime import timedelta
from typing import Any
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from aseo.api.deps import Ctx, get_ctx, get_db, get_user_session
from aseo.connectors.shopify import SCOPES, SHOP_RE
from aseo.core.config import get_settings
from aseo.core.crypto import encrypt
from aseo.core.db import set_session_tenant, system_session
from aseo.core.errors import Conflict, ConnectorError, NotFound, Unauthorized, ValidationFailed
from aseo.core.security import new_token, sha256_hex
from aseo.models import Connector, EventInbox, ExecutionRun, OAuthState, Site, User, UserSession
from aseo.models.base import utcnow
from aseo.services import audit, gsc, outbox, payments, platform_webhooks
from aseo.services import connectors as connector_svc

router = APIRouter(tags=["integrations & webhooks"])


# ------------------------------------------------------------------ OAuth: authorize


@router.post("/integrations/{provider}/authorize", summary="Start a connector OAuth flow (state + PKCE)")
def authorize(provider: str, site_id: uuid.UUID, shop: str | None = None, ctx: Ctx = Depends(get_ctx)) -> dict[str, Any]:
    site = ctx.site(site_id, "connector:manage")
    s = get_settings()
    if provider == "gsc":
        if not gsc.configured():
            sync = gsc.connect_fixture(ctx.db, site, ctx.user.id)
            return {"mode": "fixture", "synced": True, "sync_id": str(sync.id), "note": "Demo mode: labelled fixture data, not real Search Console."}
        return {"authorize_url": gsc.authorize(ctx.db, site=site, user_id=ctx.user.id)}
    if provider == "shopify":
        if not s.shopify_api_key:
            raise ValidationFailed("Shopify app is not configured (SHOPIFY_API_KEY / SHOPIFY_API_SECRET).")
        shop = (shop or "").lower()
        if not SHOP_RE.match(shop):
            raise ValidationFailed("Provide shop=<store>.myshopify.com")
        state = new_token(24)
        ctx.db.add(OAuthState(tenant_id=ctx.tenant.id, user_id=ctx.user.id, provider="shopify", state_hash=sha256_hex(state), site_id=site.id,
                              extra={"shop": shop}, expires_at=utcnow() + timedelta(minutes=10)))
        params = {"client_id": s.shopify_api_key, "scope": ",".join(SCOPES), "state": state,
                  "redirect_uri": f"{s.public_web_url}/api/v1/integrations/shopify/callback"}
        return {"authorize_url": f"https://{shop}/admin/oauth/authorize?{urlencode(params)}"}
    if provider == "github":
        if not s.github_app_slug:
            raise ValidationFailed("GitHub App is not configured (GITHUB_APP_SLUG, GITHUB_APP_ID, GITHUB_APP_PRIVATE_KEY).")
        state = new_token(24)
        ctx.db.add(OAuthState(tenant_id=ctx.tenant.id, user_id=ctx.user.id, provider="github", state_hash=sha256_hex(state), site_id=site.id,
                              expires_at=utcnow() + timedelta(minutes=30)))
        return {"authorize_url": f"https://github.com/apps/{s.github_app_slug}/installations/new?state={state}"}
    raise NotFound("Unknown provider")


def _state(db: Session, user: User, sess: UserSession, state: str, provider: str) -> tuple[OAuthState, Site]:
    if not sess.active_tenant_id:
        raise Unauthorized("Sign in first.")
    set_session_tenant(db, sess.active_tenant_id)
    row = gsc.consume_state(db, state, user.id, provider)
    site = db.get(Site, row.site_id)
    if site is None:
        raise NotFound("Site not found")
    return row, site


@router.get("/integrations/{provider}/callback", include_in_schema=True, summary="OAuth / installation callback")
def callback(provider: str, request: Request, us: tuple[User, UserSession] = Depends(get_user_session), db: Session = Depends(get_db)) -> RedirectResponse:
    user, sess = us
    q = request.query_params
    s = get_settings()
    if provider == "gsc":  # pragma: no cover - requires Google
        row, site = _state(db, user, sess, q.get("state", ""), "gsc")
        if q.get("error"):
            return RedirectResponse(f"{s.public_web_url}/app/sites/{site.id}/settings?gsc=denied")
        gsc.callback(db, site=site, state_row=row, code=q.get("code", ""))
        return RedirectResponse(f"{s.public_web_url}/app/sites/{site.id}/analytics?gsc=connected")
    if provider == "shopify":  # pragma: no cover - requires a Shopify store
        if not verify_shopify_query_hmac(dict(q), s.shopify_api_secret or ""):
            raise Unauthorized("Invalid Shopify HMAC", code="bad_signature")
        row, site = _state(db, user, sess, q.get("state", ""), "shopify")
        shop = q.get("shop", "").lower()
        if shop != row.extra.get("shop") or not SHOP_RE.match(shop):
            raise Unauthorized("Shop mismatch", code="oauth_state_invalid")
        r = httpx.post(f"https://{shop}/admin/oauth/access_token", timeout=20,
                       json={"client_id": s.shopify_api_key, "client_secret": s.shopify_api_secret, "code": q.get("code")})
        r.raise_for_status()
        connector_svc.connect(db, site=site, provider="shopify", config={"shop": shop}, secrets={"access_token": r.json()["access_token"]})
        return RedirectResponse(f"{s.public_web_url}/app/sites/{site.id}/settings?shopify=connected")
    if provider == "github":  # pragma: no cover - requires a GitHub App
        row, site = _state(db, user, sess, q.get("state", ""), "github")
        installation_id = q.get("installation_id", "")
        if not installation_id.isdigit():
            raise ValidationFailed("Missing installation id")
        existing = db.execute(select(Connector).where(Connector.site_id == site.id, Connector.provider == "github")).scalar_one_or_none()
        if existing is not None:
            existing.config = {**existing.config, "installation_id": installation_id}
            connector_svc.check(db, site, existing)
        audit.record(db, tenant_id=site.tenant_id, action="connector.github_installed", actor_id=user.id, target_type="site",
                     target_id=site.id, site_id=site.id, data={"installation_id": installation_id})
        return RedirectResponse(f"{s.public_web_url}/app/sites/{site.id}/settings?github=installed&installation_id={installation_id}")
    raise NotFound("Unknown provider")


def verify_shopify_query_hmac(params: dict[str, str], secret: str) -> bool:
    given = params.pop("hmac", "")
    msg = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
    expected = hmac.new(secret.encode(), msg.encode(), hashlib.sha256).hexdigest()
    return bool(secret) and hmac.compare_digest(expected, given)


# ------------------------------------------------------------------ webhooks


def _inbox(db: Session, provider: str, event_id: str, event_type: str, tenant_id: uuid.UUID | None, payload: dict[str, Any]) -> EventInbox:
    ev = EventInbox(tenant_id=tenant_id, provider=provider, event_id=event_id, event_type=event_type, payload=payload)
    try:
        with db.begin_nested():
            db.add(ev)
            db.flush()
    except IntegrityError as exc:
        raise Conflict("Duplicate webhook event (replay ignored).", code="webhook_replay") from exc
    return ev


def shopify_webhook(db: Session, request: Request, body: bytes) -> dict[str, Any]:
    secret = get_settings().shopify_api_secret
    sig = request.headers.get("x-shopify-hmac-sha256", "")
    expected = base64.b64encode(hmac.new((secret or "").encode(), body, hashlib.sha256).digest()).decode()
    if not secret or not hmac.compare_digest(expected, sig):
        raise Unauthorized("Invalid Shopify webhook signature", code="bad_signature")
    shop = request.headers.get("x-shopify-shop-domain", "").lower()
    topic = request.headers.get("x-shopify-topic", "")
    with system_session() as sdb:
        conn = sdb.execute(select(Connector).where(Connector.provider == "shopify", Connector.config["shop"].astext == shop)).scalars().first()
        tenant_id, site_id = (conn.tenant_id, conn.site_id) if conn else (None, None)
    ev = _inbox(db, "shopify", request.headers.get("x-shopify-webhook-id", sha256_hex(body)), topic, tenant_id, {"topic": topic, "shop": shop})
    if tenant_id and site_id:
        set_session_tenant(db, tenant_id)
        site = db.get(Site, site_id)
        if topic == "app/uninstalled":
            c = db.execute(select(Connector).where(Connector.site_id == site_id, Connector.provider == "shopify")).scalar_one()
            connector_svc.disconnect(db, c)
        elif topic.startswith(("products/", "collections/", "pages/")) and site and site.verified_at:
            from aseo.services import crawls

            try:
                crawls.schedule_crawl(db, site, trigger="event")
            except Exception:  # noqa: BLE001 — budget exhaustion etc. must not fail the webhook
                ev.error = "crawl not scheduled"
    ev.status, ev.processed_at = "processed", utcnow()
    return {"received": True}


def github_webhook(db: Session, request: Request, body: bytes) -> dict[str, Any]:
    secret = get_settings().github_webhook_secret
    sig = request.headers.get("x-hub-signature-256", "")
    expected = "sha256=" + hmac.new((secret or "").encode(), body, hashlib.sha256).hexdigest()
    if not secret or not hmac.compare_digest(expected, sig):
        raise Unauthorized("Invalid GitHub webhook signature", code="bad_signature")
    event = request.headers.get("x-github-event", "")
    payload = json.loads(body or b"{}")
    repo = (payload.get("repository") or {}).get("full_name", "")
    ev = _inbox(db, "github", request.headers.get("x-github-delivery", sha256_hex(body)), event, None, {"event": event, "repo": repo})
    relevant = (event == "pull_request" and payload.get("action") == "closed") or (
        event == "deployment_status" and (payload.get("deployment_status") or {}).get("state") == "success")
    queued = 0
    if relevant and "/" in repo:
        owner, name = repo.split("/", 1)
        with system_session() as sdb:
            conns = sdb.execute(select(Connector).where(Connector.provider == "github", Connector.config["owner"].astext == owner,
                                                        Connector.config["repo"].astext == name)).scalars().all()
            for c in conns:
                runs = sdb.execute(select(ExecutionRun).where(ExecutionRun.tenant_id == c.tenant_id, ExecutionRun.status == "awaiting_deploy",
                                                              ExecutionRun.connector_provider == "github")).scalars().all()
                for r in runs:
                    outbox.enqueue(sdb, "execution.verify", {"execution_id": str(r.id)}, tenant_id=c.tenant_id,
                                   dedupe_key=f"ghverify:{r.id}:{ev.event_id}")
                    queued += 1
    ev.status, ev.processed_at = "processed", utcnow()
    if queued:
        outbox.kick()
    return {"received": True, "verifications_queued": queued}


platform_webhooks.HANDLERS["shopify"] = shopify_webhook
platform_webhooks.HANDLERS["github"] = github_webhook


@router.post("/webhooks/{provider}", summary="Inbound webhooks (signature-verified, replay-protected)")
async def webhook(provider: str, request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    payload = await request.body()
    if provider == "billing":
        sig = request.headers.get("stripe-signature") or request.headers.get("x-lodestar-signature")
        return payments.handle_webhook(db, "billing", payload, sig)
    if provider in platform_webhooks.HANDLERS:
        return platform_webhooks.HANDLERS[provider](db, request, payload)
    raise NotFound("Unknown webhook provider")


_ = (encrypt, ConnectorError)
