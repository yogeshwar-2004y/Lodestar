"""M1 acceptance against the WordPress companion-plugin fixture:
register/verify -> connect -> crawl -> detect missing description -> deterministic draft ->
policy/approval -> write -> verify live HTML -> before/after + audit trail -> rollback."""

from tests.conftest import drain


def _finding(api, site_id, rule):
    fs = api.get(f"/sites/{site_id}/findings").json()
    return next(f for f in fs if f["rule_key"] == rule)


def test_m1_end_to_end(wp_site, wp):
    api, site = wp_site
    sid = site["id"]

    # detect missing meta description on real crawled pages
    f = _finding(api, sid, "missing_meta_description")
    detail = api.get(f"/findings/{f['id']}").json()
    urls = {o["url"] for o in detail["occurrences"]}
    target = f"{wp.base}/subscriptions/"
    assert target in urls
    assert f["kind"] == "deterministic"

    # post-crawl workflow ran Audit + Strategy agents and queued proposals (assist mode => approval needed)
    wfs = api.get(f"/sites/{sid}/workflows").json()
    assert wfs and wfs[0]["status"] == "completed"
    assert {r["agent"] for r in wfs[0]["agent_runs"]} >= {"audit", "strategy"}
    pending = api.get(f"/change-sets?site_id={sid}&status=pending_approval").json()["items"]
    assert pending, "execution agent should have proposed metadata fixes"

    # propose explicitly for the target page with an AI/deterministic draft
    r = api.post("/change-sets", {"site_id": sid, "url": target, "action_type": "meta_description", "finding_id": f["id"]})
    assert r.status_code == 201, r.text
    cs = r.json()
    assert cs["status"] == "pending_approval", cs["policy_decision"]
    v = cs["current_version"]
    assert v["before"] == {"meta_description": ""}
    draft = v["patch"]["after"]["meta_description"]
    assert 25 <= len(draft) <= 300
    assert v["validation"]["passed"] is True
    assert cs["connector"]["mode"] == "fixture"
    assert cs["policy_decision"]["decision"] == "require_approval"

    # execute before approval is refused
    r = api.post(f"/change-sets/{cs['id']}/execute", {"patch_hash": v["patch_hash"]})
    assert r.status_code == 409 and r.json()["error"]["code"] == "not_approved"

    # approve the exact hash
    r = api.post(f"/change-sets/{cs['id']}/approve", {"patch_hash": v["patch_hash"], "reason": "Looks accurate"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "approved"

    r = api.post(f"/change-sets/{cs['id']}/execute", {"patch_hash": v["patch_hash"]}, headers={"Idempotency-Key": "exec-1"})
    assert r.status_code == 202, r.text
    exec_id = r.json()["id"]
    # replaying the same request returns the same execution
    r2 = api.post(f"/change-sets/{cs['id']}/execute", {"patch_hash": v["patch_hash"]}, headers={"Idempotency-Key": "exec-1"})
    assert r2.json()["id"] == exec_id

    drain()
    ex = api.get(f"/executions/{exec_id}").json()
    assert ex["status"] == "succeeded", ex
    assert ex["verification"]["verified"] is True
    assert ex["verification"]["observed"]["live_html"]["meta_description"] == draft
    assert ex["connector_mode"] == "fixture"
    # the fixture really stored it
    assert wp.post(3)["seo"]["description"] == draft

    detail = api.get(f"/change-sets/{cs['id']}").json()
    assert detail["status"] == "completed"
    fixed = api.get(f"/findings/{f['id']}").json()
    assert fixed["finding"]["affected_count"] == len(urls) - 1
    assert any(o["url"] == target and o["status"] == "fixed" for o in fixed["occurrences"])
    assert detail["rollback_available"] is True

    # audit trail covers the lifecycle
    events = [e["action"] for e in api.get(f"/audit-events?target_id={cs['id']}").json()["items"]]
    for action in ("change_set.proposed", "change_set.approved", "execution.apply_queued", "execution.write_applied", "execution.verified"):
        assert action in events, events

    # rollback restores the previous (empty) value and verifies it live
    r = api.post(f"/change-sets/{cs['id']}/rollback", {"reason": "test restore"})
    assert r.status_code == 202, r.text
    drain()
    rb = api.get(f"/executions/{r.json()['id']}").json()
    assert rb["status"] == "succeeded", rb
    assert wp.post(3)["seo"]["description"] == ""
    assert api.get(f"/change-sets/{cs['id']}").json()["status"] == "rolled_back"

    chain = api.get("/audit-events/verify").json()
    assert chain["valid"] is True and chain["checked"] > 5
