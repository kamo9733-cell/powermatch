"""Endpoints the manager UI needed: GET /me and POST /alerts/ack (found by the front-end review)."""
from fastapi.testclient import TestClient
from test_security_api import Clock, invite, mkloc, pair, signup

from tablesight.platform.app import Outbox, create_app


def setup():
    ob, clk = Outbox(), Clock()
    c = TestClient(create_app(outbox=ob, clock=clk))
    owner = signup(c, ob, "o@x.com")
    lid = mkloc(c, owner)
    dev, _ = pair(c, owner, lid)
    t = clk.t
    c.post("/edge/events", json=[
        {"event_id": "a1", "t": t - 5, "table_id": "T1", "kind": "needs_attention", "detail": {"section": "A"}},
        {"event_id": "b1", "t": t - 4, "table_id": "T9", "kind": "needs_attention", "detail": {"section": "B"}},
        {"event_id": "s1", "t": t - 3, "table_id": "T1", "kind": "seated", "detail": {"section": "A"}},
    ], headers=dev).raise_for_status()
    return c, ob, owner, lid


def test_me_reports_role_and_permissions():
    c, _, owner, _ = setup()
    me = c.get("/me", headers=owner).json()
    assert me["role"] == "owner" and me["email"] == "o@x.com" and "alerts.ack" in me["permissions"]
    assert c.get("/me").status_code == 401


def test_ack_is_idempotent_and_audited():
    c, _, owner, lid = setup()
    r1 = c.post("/alerts/ack", params={"location_id": lid, "event_id": "a1"}, headers=owner)
    r2 = c.post("/alerts/ack", params={"location_id": lid, "event_id": "a1"}, headers=owner)
    assert r1.json() == {"ok": True, "already": False} and r2.json()["already"] is True
    assert "alert.ack" in {a["action"] for a in c.get("/audit", headers=owner).json()}


def test_ack_rejects_non_alert_and_unknown_events():
    c, _, owner, lid = setup()
    for ev in ("s1", "nope"):
        assert c.post("/alerts/ack", params={"location_id": lid, "event_id": ev}, headers=owner).status_code == 404


def test_server_can_ack_only_own_section_and_foreign_tenant_gets_404():
    c, ob, owner, lid = setup()
    srv = invite(c, ob, owner, "s@x.com", "server", lid)
    uid = c.get("/me", headers=srv).json()["user_id"]
    assert c.patch(f"/members/{uid}", params={"role": "server", "section": "A"}, headers=owner).status_code == 200
    assert c.post("/alerts/ack", params={"location_id": lid, "event_id": "b1"}, headers=srv).status_code == 404
    assert c.post("/alerts/ack", params={"location_id": lid, "event_id": "a1"}, headers=srv).status_code == 200
    other = signup(c, ob, "z@x.com")
    assert c.post("/alerts/ack", params={"location_id": lid, "event_id": "a1"}, headers=other).status_code == 404
