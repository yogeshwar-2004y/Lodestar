"""Approval binding, replay, RBAC, tenant isolation, kill switch and failure injection."""

import json
import uuid

import pytest
from sqlalchemy import create_engine, text

from tests.conftest import APP_URL, drain


def _propose(api, site, wp, path="/subscriptions/", value=None):
    body = {"site_id": site["id"], "url": f"{wp.base}{path}", "action_type": "meta_description"}
    if value:
        body["value"] = value
    r = api.post("/change-sets", body)
    assert r.status_code == 201, r.text
    return r.json()


VALUE = "Flexible coffee subscriptions: choose a roast, pick a delivery schedule and pause anytime. Beans ship within 48 hours."


def test_approval_bound_to_hash_and_revision_invalidates(wp_site, wp):
    api, site = wp_site
    cs = _propose(api, site, wp, value=VALUE)
    h1 = cs["current_version"]["patch_hash"]

    # wrong hash cannot be approved
    r = api.post(f"/change-sets/{cs['id']}/approve", {"patch_hash": "0" * 64})
    assert r.status_code == 409 and r.json()["error"]["code"] == "patch_hash_mismatch"

    assert api.post(f"/change-sets/{cs['id']}/approve", {"patch_hash": h1}).status_code == 200
    # revising creates a new immutable version; old approval no longer applies
    r = api.post(f"/change-sets/{cs['id']}/validate", {"value": VALUE.replace("Flexible", "Simple")})
    revised = r.json()
    h2 = revised["current_version"]["patch_hash"]
    assert h2 != h1 and revised["status"] == "pending_approval" and len(revised["versions"]) == 2
    r = api.post(f"/change-sets/{cs['id']}/execute", {"patch_hash": h1})
    assert r.status_code == 409
    r = api.post(f"/change-sets/{cs['id']}/execute", {"patch_hash": h2})
    assert r.status_code == 409 and r.json()["error"]["code"] == "not_approved"


def test_execute_rejects_patch_content(wp_site, wp):
    api, site = wp_site
    cs = _propose(api, site, wp, value=VALUE)
    h = cs["current_version"]["patch_hash"]
    api.post(f"/change-sets/{cs['id']}/approve", {"patch_hash": h})
    r = api.post(f"/change-sets/{cs['id']}/execute", {"patch_hash": h, "after": {"meta_description": "evil"}})
    assert r.status_code == 422


def test_patch_versions_and_audit_are_immutable_in_db(wp_site, wp):
    api, site = wp_site
    _propose(api, site, wp, value=VALUE)
    eng = create_engine(APP_URL)
    with eng.connect() as c:
        c.execute(text("select set_config('app.bypass_rls','on',false)"))
        with pytest.raises(Exception, match="immutable"):
            c.execute(text("update patch_versions set patch = '{}'::jsonb"))
        c.rollback()
        c.execute(text("select set_config('app.bypass_rls','on',false)"))
        with pytest.raises(Exception, match="append-only"):
            c.execute(text("update audit_events set action = 'x'"))
        c.rollback()
        c.execute(text("select set_config('app.bypass_rls','on',false)"))
        with pytest.raises(Exception, match="append-only"):
            c.execute(text("delete from approvals"))
    eng.dispose()


def test_stale_resource_version_blocks_write(wp_site, wp):
    api, site = wp_site
    cs = _propose(api, site, wp, path="/brew-guides/pour-over/", value=VALUE)
    h = cs["current_version"]["patch_hash"]
    api.post(f"/change-sets/{cs['id']}/approve", {"patch_hash": h})
    wp.module.STATE["posts"][4]["seo"]["description"] = "Edited by a human in WordPress meanwhile."
    r = api.post(f"/change-sets/{cs['id']}/execute", {"patch_hash": h})
    drain()
    ex = api.get(f"/executions/{r.json()['id']}").json()
    assert ex["status"] == "failed" and "stale_resource_version" in ex["error"]
    assert wp.post(4)["seo"]["description"] == "Edited by a human in WordPress meanwhile."


def test_connector_429_retries_then_succeeds(wp_site, wp):
    api, site = wp_site
    cs = _propose(api, site, wp, value=VALUE)
    h = cs["current_version"]["patch_hash"]
    api.post(f"/change-sets/{cs['id']}/approve", {"patch_hash": h})
    wp.faults(429, 2)  # resolve call fails twice, then works
    r = api.post(f"/change-sets/{cs['id']}/execute", {"patch_hash": h})
    drain()
    ex = api.get(f"/executions/{r.json()['id']}").json()
    assert ex["status"] == "succeeded", ex
    assert ex["attempt"] == 3


def test_connector_500_exhausts_to_dead_letter(wp_site, wp):
    api, site = wp_site
    cs = _propose(api, site, wp, value=VALUE)
    h = cs["current_version"]["patch_hash"]
    api.post(f"/change-sets/{cs['id']}/approve", {"patch_hash": h})
    wp.faults(500, 50)
    r = api.post(f"/change-sets/{cs['id']}/execute", {"patch_hash": h})
    drain()
    wp.faults(None, 0)
    ex = api.get(f"/executions/{r.json()['id']}").json()
    assert ex["status"] == "dead_letter" and ex["attempt"] == 3
    assert wp.post(3)["seo"]["description"] == ""
    notes = api.get("/notifications").json()["items"]
    assert any(n["kind"] == "execution_failed" for n in notes)


def test_kill_switch_blocks_and_cancels(wp_site, wp):
    api, site = wp_site
    cs = _propose(api, site, wp, value=VALUE)
    h = cs["current_version"]["patch_hash"]
    api.post(f"/change-sets/{cs['id']}/approve", {"patch_hash": h})
    r = api.post(f"/change-sets/{cs['id']}/execute", {"patch_hash": h})
    assert r.status_code == 202
    r = api.post("/organizations/current/kill-switch?engaged=true")
    assert r.json()["cancelled_executions"] == 1
    drain()
    assert wp.post(3)["seo"]["description"] == ""
    cs2 = _propose(api, site, wp, path="/contact/", value=VALUE)
    assert cs2["status"] == "blocked"
    api.post("/organizations/current/kill-switch?engaged=false")


def test_autopilot_auto_executes_only_whitelisted(wp_site, wp):
    api, site = wp_site
    r = api.put(f"/sites/{site['id']}/automations/policy", {"mode": "autopilot", "auto_actions": ["meta_description"],
                                                             "path_scope": ["/subscriptions/"], "max_risk_score": 0.3})
    assert r.status_code == 200, r.text
    cs = _propose(api, site, wp, value=VALUE)
    assert cs["status"] == "queued", cs["policy_decision"]
    assert cs["approvals"][0]["decision"] == "auto_approved"
    drain()
    assert api.get(f"/change-sets/{cs['id']}").json()["status"] == "completed"
    # outside path scope -> approval required
    other = _propose(api, site, wp, path="/brew-guides/pour-over/", value=VALUE)
    assert other["status"] == "pending_approval"
    # title is not whitelisted -> approval required
    t = api.post("/change-sets", {"site_id": site["id"], "url": f"{wp.base}/subscriptions/", "action_type": "title",
                                  "value": "Coffee Subscriptions | Northwind Coffee Roasters"}).json()
    assert t["status"] == "pending_approval"


def test_rbac_roles(wp_site, wp, client):
    owner, site = wp_site
    for role, can_propose, can_approve in (("viewer", False, False), ("analyst", True, False), ("editor", True, True)):
        email = f"{role}{uuid.uuid4().hex[:6]}@example.com"
        r = owner.post("/organizations/current/members", {"email": email, "name": role, "role": role, "password": "correct horse battery"})
        assert r.status_code == 201, r.text
        tok = client.post("/api/v1/auth/login", json={"email": email, "password": "correct horse battery"}).json()["token"]
        h = {"Authorization": f"Bearer {tok}"}
        body = {"site_id": site["id"], "url": f"{wp.base}/contact/", "action_type": "meta_description", "value": VALUE}
        r = client.post("/api/v1/change-sets", json=body, headers=h)
        assert (r.status_code == 201) == can_propose, (role, r.text)
        cs = _propose(owner, site, wp, path="/contact/", value=VALUE + f" {role}")
        r = client.post(f"/api/v1/change-sets/{cs['id']}/approve", json={"patch_hash": cs["current_version"]["patch_hash"]}, headers=h)
        assert (r.status_code == 200) == can_approve, (role, r.text)
        assert client.post("/api/v1/organizations/current/kill-switch?engaged=true", headers=h).status_code == 403


def test_tenant_isolation_api_and_rls(wp_site, make_user):
    owner, site = wp_site
    other = make_user("Other Org")
    assert other.get(f"/sites/{site['id']}").status_code == 404
    assert other.get(f"/sites/{site['id']}/findings").status_code == 404
    assert all(s["id"] != site["id"] for s in other.get("/sites").json())
    f = owner.get(f"/sites/{site['id']}/findings").json()[0]
    assert other.get(f"/findings/{f['id']}").status_code == 404
    cs = owner.get(f"/change-sets?site_id={site['id']}").json()["items"]
    if cs:
        assert other.get(f"/change-sets/{cs[0]['id']}").status_code == 404
        assert other.post(f"/change-sets/{cs[0]['id']}/approve", {"patch_hash": "0" * 64}).status_code == 404
    # tenant id in a body is not authority
    r = other.post("/change-sets", {"site_id": site["id"], "url": "x", "action_type": "meta_description", "value": "x" * 80,
                                    "tenant_id": owner.session["organization"]["id"]})
    assert r.status_code == 404
    # Database RLS: the app role sees nothing without a tenant, and only its tenant with one
    eng = create_engine(APP_URL)
    with eng.connect() as c:
        assert c.execute(text("select count(*) from sites")).scalar() == 0
        c.execute(text("select set_config('app.tenant_id', :t, false)"), {"t": other.session["organization"]["id"]})
        assert c.execute(text("select count(*) from sites where id = :s"), {"s": site["id"]}).scalar() == 0
        c.execute(text("select set_config('app.tenant_id', :t, false)"), {"t": owner.session["organization"]["id"]})
        assert c.execute(text("select count(*) from sites where id = :s"), {"s": site["id"]}).scalar() == 1
        with pytest.raises(Exception):
            c.execute(text("insert into sites (id, tenant_id, name, domain, base_url, platform, status, crawl_settings, health_breakdown,"
                           " locale, is_demo, resource_lock_version, created_at, updated_at) values (gen_random_uuid(), :t, 'x', 'x.com',"
                           " 'https://x.com/', 'public', 'pending', '{}', '{}', 'en', false, 0, now(), now())"),
                      {"t": other.session["organization"]["id"]})
    eng.dispose()


def test_agency_client_workspace_boundary(make_user, client, wp):
    agency = make_user("Agency Co", kind="agency")
    ws_a = agency.post("/workspaces", {"name": "Client A"}).json()
    ws_b = agency.post("/workspaces", {"name": "Client B"}).json()
    sa = agency.post("/sites", {"name": "A", "url": "https://client-a.example", "workspace_id": ws_a["id"]}).json()
    sb = agency.post("/sites", {"name": "B", "url": "https://client-b.example", "workspace_id": ws_b["id"]}).json()
    email = f"client{uuid.uuid4().hex[:6]}@example.com"
    agency.post("/organizations/current/members", {"email": email, "name": "Client A user", "role": "client",
                                                   "password": "correct horse battery", "workspace_ids": [ws_a["id"]]})
    tok = client.post("/api/v1/auth/login", json={"email": email, "password": "correct horse battery"}).json()["token"]
    h = {"Authorization": f"Bearer {tok}"}
    sites = client.get("/api/v1/sites", headers=h).json()
    assert [s["id"] for s in sites] == [sa["id"]]
    assert client.get(f"/api/v1/sites/{sb['id']}", headers=h).status_code == 404
    assert [w["id"] for w in client.get("/api/v1/workspaces", headers=h).json()] == [ws_a["id"]]
    assert client.post("/api/v1/sites/" + sa["id"] + "/crawls", json={}, headers=h).status_code == 403
    assert client.get("/api/v1/audit-events", headers=h).status_code == 403


def test_secrets_never_returned_or_logged(wp_site, capsys):
    api, site = wp_site
    conns = api.get(f"/sites/{site['id']}/connectors").json()
    blob = json.dumps(conns)
    assert "fixture-app-password" not in blob
    assert conns[0]["secrets"][0]["name"] == "app_password" and len(conns[0]["secrets"][0]["fingerprint"]) == 8
    events = json.dumps(api.get("/audit-events").json())
    assert "fixture-app-password" not in events
    assert "fixture-app-password" not in capsys.readouterr().out


def test_crawl_dedup_and_budget(wp_site):
    api, site = wp_site
    a = api.post(f"/sites/{site['id']}/crawls", {}).json()
    b = api.post(f"/sites/{site['id']}/crawls", {}).json()
    assert a["id"] == b["id"] and b["deduplicated"] is True
    usage = api.get("/usage").json()
    assert usage["reconciliation"]["consistent"] is True
    reasons = [e["reason"] for e in usage["ledger"]]
    assert "crawl" in reasons and "refund" in reasons
    drain()


def test_csrf_required_for_cookie_auth(client, make_user):
    api = make_user()
    client.cookies.clear()
    r = client.post("/api/v1/auth/login", json={"email": api.email, "password": "correct horse battery"})
    assert r.status_code == 200
    # cookie set by login; unsafe call without CSRF header is refused
    r = client.post("/api/v1/workspaces", json={"name": "No CSRF"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "csrf_failed"
    r = client.post("/api/v1/workspaces", json={"name": "With CSRF"}, headers={"X-CSRF-Token": client.cookies.get("ls_csrf")})
    assert r.status_code == 201
    client.cookies.clear()
