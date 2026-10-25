"""Google Search Console integration.

* OAuth 2.0 authorization-code flow with PKCE and hashed, single-use, expiring state.
  Scope: ``webmasters.readonly`` only.
* Search Analytics sync (date, date+page, query+page). Data is treated as delayed (we stop
  3 days before today) and incomplete (anonymised queries are not reported by Google).
* Demo mode without Google credentials loads clearly labelled ``demo_fixture`` rows — never
  presented as real Search Console data.
"""

from __future__ import annotations

import base64
import hashlib
import math
import random
import re
import uuid
from collections import defaultdict
from datetime import date, timedelta
from typing import Any
from urllib.parse import quote, urlencode

import httpx
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from aseo.core.config import get_settings
from aseo.core.crypto import decrypt, encrypt
from aseo.core.errors import ConnectorError, Forbidden, ValidationFailed
from aseo.core.security import new_token, sha256_hex
from aseo.models import Connector, DataSourceSync, KeywordCluster, KeywordQuery, OAuthState, Page, SearchMetric, Site
from aseo.models.base import utcnow
from aseo.services import audit, outbox
from aseo.services import secrets as secret_store

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"  # noqa: S105 — endpoint, not a secret
API = "https://www.googleapis.com/webmasters/v3"
SCOPE = "https://www.googleapis.com/auth/webmasters.readonly"
DELAY_DAYS = 3


def redirect_uri() -> str:
    return f"{get_settings().public_web_url}/api/v1/integrations/gsc/callback"


def configured() -> bool:
    s = get_settings()
    return bool(s.google_client_id and s.google_client_secret)


def authorize(db: Session, *, site: Site, user_id: uuid.UUID) -> str:
    verifier = new_token(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = new_token(24)
    db.add(OAuthState(tenant_id=site.tenant_id, user_id=user_id, provider="gsc", state_hash=sha256_hex(state),
                      code_verifier_enc=encrypt(verifier), site_id=site.id, expires_at=utcnow() + timedelta(minutes=10)))
    params = {"client_id": get_settings().google_client_id, "redirect_uri": redirect_uri(), "response_type": "code", "scope": SCOPE,
              "access_type": "offline", "prompt": "consent", "state": state, "code_challenge": challenge, "code_challenge_method": "S256",
              "include_granted_scopes": "true"}
    return f"{AUTH_URL}?{urlencode(params)}"


def consume_state(db: Session, state: str, user_id: uuid.UUID, provider: str) -> OAuthState:
    row = db.execute(select(OAuthState).where(OAuthState.state_hash == sha256_hex(state), OAuthState.provider == provider)).scalar_one_or_none()
    if row is None or row.used_at is not None or row.expires_at < utcnow():
        raise Forbidden("OAuth state is invalid, expired or already used.", code="oauth_state_invalid")
    if row.user_id != user_id:
        raise Forbidden("OAuth flow was started by a different user.", code="oauth_state_invalid")
    row.used_at = utcnow()
    return row


def callback(db: Session, *, site: Site, state_row: OAuthState, code: str) -> Connector:  # pragma: no cover - requires Google
    s = get_settings()
    r = httpx.post(TOKEN_URL, timeout=20, data={"client_id": s.google_client_id, "client_secret": s.google_client_secret, "code": code,
                                                "code_verifier": decrypt(state_row.code_verifier_enc or ""), "grant_type": "authorization_code",
                                                "redirect_uri": redirect_uri()})
    if r.status_code != 200:
        raise ConnectorError("Google rejected the authorization code.", code="oauth_exchange_failed")
    tokens = r.json()
    refresh = tokens.get("refresh_token")
    if not refresh:
        raise ConnectorError("Google did not return a refresh token; remove access and try again.", code="oauth_no_refresh_token")
    prop = _match_property(tokens["access_token"], site)
    connector = _connector(db, site, mode="live", prop=prop)
    secret_store.put_secret(db, tenant_id=site.tenant_id, connector_id=connector.id, name="refresh_token", value=refresh)
    connector.status = "connected"
    connector.scopes = [SCOPE]
    audit.record(db, tenant_id=site.tenant_id, action="connector.connected", actor_id=state_row.user_id, target_type="connector",
                 target_id=connector.id, site_id=site.id, data={"provider": "gsc", "property": prop})
    schedule_sync(db, site)
    return connector


def _match_property(access_token: str, site: Site) -> str:  # pragma: no cover - requires Google
    r = httpx.get(f"{API}/sites", headers={"Authorization": f"Bearer {access_token}"}, timeout=20)
    entries = [e["siteUrl"] for e in r.json().get("siteEntry", []) if e.get("permissionLevel") != "siteUnverifiedUser"]
    host = site.domain.split(":")[0]
    bare = host[4:] if host.startswith("www.") else host
    for candidate in (f"sc-domain:{bare}", site.base_url, f"https://{host}/", f"http://{host}/"):
        if candidate in entries:
            return candidate
    raise ConnectorError(f"No verified Search Console property found for {host}.", code="gsc_property_missing")


def _connector(db: Session, site: Site, *, mode: str, prop: str | None) -> Connector:
    c = db.execute(select(Connector).where(Connector.site_id == site.id, Connector.provider == "gsc")).scalar_one_or_none()
    if c is None:
        c = Connector(tenant_id=site.tenant_id, site_id=site.id, provider="gsc")
        db.add(c)
    c.mode = mode
    c.config = {"property": prop}
    c.status = "connected"
    c.last_checked_at = utcnow()
    db.flush()
    return c


def schedule_sync(db: Session, site: Site) -> DataSourceSync:
    sync = DataSourceSync(tenant_id=site.tenant_id, site_id=site.id, source="gsc", status="queued")
    db.add(sync)
    db.flush()
    outbox.enqueue(db, "gsc.sync", {"sync_id": str(sync.id)}, tenant_id=site.tenant_id, dedupe_key=f"gsc:{sync.id}")
    return sync


def _access_token(db: Session, connector: Connector) -> str:  # pragma: no cover - requires Google
    s = get_settings()
    refresh = secret_store.get_secret(db, connector.id, "refresh_token")
    if not refresh:
        raise ConnectorError("Search Console refresh token missing; reconnect.", code="connector_not_configured")
    r = httpx.post(TOKEN_URL, timeout=20, data={"client_id": s.google_client_id, "client_secret": s.google_client_secret,
                                                "refresh_token": refresh, "grant_type": "refresh_token"})
    if r.status_code != 200:
        raise ConnectorError("Search Console access was revoked; reconnect.", code="connector_unauthorized")
    return r.json()["access_token"]


def _query(token: str, prop: str, body: dict[str, Any]) -> list[dict[str, Any]]:  # pragma: no cover - requires Google
    rows: list[dict[str, Any]] = []
    start = 0
    while True:
        r = httpx.post(f"{API}/sites/{quote(prop, safe='')}/searchAnalytics/query", headers={"Authorization": f"Bearer {token}"},
                       json={**body, "rowLimit": 25000, "startRow": start, "dataState": "final"}, timeout=60)
        if r.status_code == 429:
            raise ConnectorError("Search Console quota exceeded", retryable=True)
        r.raise_for_status()
        batch = r.json().get("rows", [])
        rows.extend(batch)
        if len(batch) < 25000 or len(rows) >= 100_000:
            return rows
        start += len(batch)


def run_sync(sync_id: uuid.UUID, tenant_id: uuid.UUID) -> None:
    from aseo.core.db import tenant_session

    with tenant_session(tenant_id) as db:
        sync = db.get(DataSourceSync, sync_id)
        site = db.get(Site, sync.site_id)
        sync.status, sync.started_at = "running", utcnow()
        connector = db.execute(select(Connector).where(Connector.site_id == site.id, Connector.provider == "gsc")).scalar_one_or_none()
        end = date.today() - timedelta(days=DELAY_DAYS)
        start = end - timedelta(days=180)
        if connector is None or connector.mode == "fixture":
            daily, by_page, queries = _fixture_rows(db, site, start, end)
            source = "demo_fixture"
        else:  # pragma: no cover - requires Google
            token = _access_token(db, connector)
            prop = connector.config["property"]
            base = {"startDate": start.isoformat(), "endDate": end.isoformat()}
            daily = [(date.fromisoformat(r["keys"][0]), "", r) for r in _query(token, prop, {**base, "dimensions": ["date"]})]
            by_page = [(date.fromisoformat(r["keys"][0]), r["keys"][1], r) for r in _query(token, prop, {**base, "dimensions": ["date", "page"]})]
            queries = _query(token, prop, {"startDate": (end - timedelta(days=28)).isoformat(), "endDate": end.isoformat(), "dimensions": ["query", "page"]})
            source = "gsc"
        db.execute(delete(SearchMetric).where(SearchMetric.site_id == site.id, SearchMetric.source == source))
        for d, page, r in daily + by_page:
            db.add(SearchMetric(tenant_id=site.tenant_id, site_id=site.id, date=d, page=page, query="", clicks=int(r["clicks"]),
                                impressions=int(r["impressions"]), ctr=float(r.get("ctr", 0)), position=float(r.get("position") or 0) or None,
                                source=source))
        _store_queries(db, site, queries, source, end)
        sync.rows = len(daily) + len(by_page) + len(queries)
        sync.data_through = end
        sync.status, sync.finished_at = "completed", utcnow()
        sync.is_fixture = source == "demo_fixture"


def _fixture_rows(db: Session, site: Site, start: date, end: date) -> tuple[list[Any], list[Any], list[dict[str, Any]]]:
    """Deterministic, plainly-labelled demo series (seeded by site id). Flat with weekly
    seasonality and noise — it deliberately shows no 'improvement' after fixes."""
    rng = random.Random(site.id.int)
    pages = [p.url for p in db.execute(select(Page).where(Page.site_id == site.id, Page.status_code == 200)).scalars()][:12] or [site.base_url]
    weights = [rng.uniform(0.3, 1.0) for _ in pages]
    daily, by_page = [], []
    d = start
    while d <= end:
        season = 1 + 0.18 * math.sin(d.weekday() / 7 * 2 * math.pi)
        tot_c = tot_i = 0
        pos_acc = 0.0
        for url, w in zip(pages, weights, strict=False):
            imps = int(rng.gauss(140 * w * season, 18))
            imps = max(0, imps)
            pos = max(1.0, rng.gauss(9 - 5 * w, 1.2))
            ctr = max(0.0, min(0.4, 0.28 / pos + rng.gauss(0, 0.004)))
            clicks = int(imps * ctr)
            by_page.append((d, url, {"clicks": clicks, "impressions": imps, "ctr": ctr, "position": pos}))
            tot_c += clicks
            tot_i += imps
            pos_acc += pos * imps
        daily.append((d, "", {"clicks": tot_c, "impressions": tot_i, "ctr": tot_c / tot_i if tot_i else 0, "position": pos_acc / tot_i if tot_i else None}))
        d += timedelta(days=1)
    terms = ["coffee subscription", "coffee beans online", "pour over ratio", "how to brew pour over", "fresh roasted coffee",
             "single origin coffee", "coffee delivery", "pause coffee subscription", "best coffee for pour over", "portland coffee roaster",
             "light roast vs dark roast", "coffee gift subscription"]
    queries = []
    for t in terms:
        page = rng.choice(pages)
        imps = rng.randint(60, 2400)
        pos = round(rng.uniform(2.5, 18), 1)
        ctr = max(0.002, min(0.3, 0.25 / pos * rng.uniform(0.3, 1.2)))
        queries.append({"keys": [t, page], "clicks": int(imps * ctr), "impressions": imps, "ctr": ctr, "position": pos})
    return daily, by_page, queries


_STOP = {"a", "an", "the", "for", "to", "of", "in", "on", "and", "or", "vs", "how", "what", "best", "is", "with"}


def _head_term(q: str) -> str:
    words = [w for w in re.findall(r"[a-z0-9]+", q.lower()) if w not in _STOP]
    return words[0] if words else q.lower()


def _store_queries(db: Session, site: Site, rows: list[dict[str, Any]], source: str, end: date) -> None:
    db.execute(delete(KeywordQuery).where(KeywordQuery.site_id == site.id, KeywordQuery.source == source))
    db.execute(delete(KeywordCluster).where(KeywordCluster.site_id == site.id, KeywordCluster.source == source))
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        groups[_head_term(r["keys"][0])].append(r)
    for head, items in groups.items():
        clicks = sum(int(i["clicks"]) for i in items)
        imps = sum(int(i["impressions"]) for i in items)
        avg_pos = sum(float(i["position"]) * int(i["impressions"]) for i in items) / imps if imps else None
        # opportunity: many impressions at reachable positions with low CTR (no volume estimates)
        opp = round(min(1.0, (imps / 2000) * (1 - min(1.0, clicks / imps / 0.1 if imps else 1)) * (1 if (avg_pos or 99) <= 15 else 0.4)), 2) if imps else 0
        cl = KeywordCluster(tenant_id=site.tenant_id, site_id=site.id, name=head, intent=None, queries_count=len(items), clicks=clicks,
                            impressions=imps, opportunity_score=opp, source=source)
        db.add(cl)
        db.flush()
        for i in items:
            db.add(KeywordQuery(tenant_id=site.tenant_id, site_id=site.id, cluster_id=cl.id, query=i["keys"][0], page_url=i["keys"][1],
                                source=source, clicks=int(i["clicks"]), impressions=int(i["impressions"]), ctr=float(i["ctr"]),
                                position=float(i["position"]), period_start=end - timedelta(days=28), period_end=end))


def connect_fixture(db: Session, site: Site, user_id: uuid.UUID) -> DataSourceSync:
    if not get_settings().demo_mode:
        raise ValidationFailed("Search Console is not configured (GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET).")
    c = _connector(db, site, mode="fixture", prop=None)
    audit.record(db, tenant_id=site.tenant_id, action="connector.connected", actor_id=user_id, target_type="connector", target_id=c.id,
                 site_id=site.id, data={"provider": "gsc", "mode": "fixture"})
    return schedule_sync(db, site)


@outbox.handler("gsc.sync")
def _h_sync(payload: dict[str, Any], tenant_id: uuid.UUID | None) -> None:
    assert tenant_id
    run_sync(uuid.UUID(payload["sync_id"]), tenant_id)
