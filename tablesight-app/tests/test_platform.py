import pytest
from fastapi.testclient import TestClient

from tablesight.platform import security
from tablesight.platform.app import Outbox, create_app

PW = "correct-horse-battery"


@pytest.fixture
def env():
    ob = Outbox()
    app = create_app(outbox=ob)
    return TestClient(app), ob, app


def signup(c, ob, email, org="Org"):
    c.post("/signup", json={"email": email, "password": PW, "org_name": org}).raise_for_status()
    tok = [m for m in ob.sent if m["to"] == email and m["kind"] == "verify_email"][-1]["token"]
    c.post("/verify-email", params={"token": tok}).raise_for_status()
    r = c.post("/login", json={"email": email, "password": PW})
    r.raise_for_status()
    return {"Authorization": "Bearer " + r.json()["token"]}


def mkloc(c, h, name="L1"):
    return c.post("/locations", params={"name": name}, headers=h).json()["id"]


def pair(c, h, lid):
    code = c.post("/pairing", params={"location_id": lid}, headers=h).json()["code"]
    return {"Authorization": "Bearer " + c.post("/edge/pair", params={"code": code}).json()["token"]}


def ev(i, kind="seated", **d):
    return {"event_id": f"e{i}", "t": float(i), "table_id": "T1", "kind": kind, "detail": d}


def test_tenant_isolation_across_every_resource(env):
    c, ob, _ = env
    a, b = signup(c, ob, "a@x.com"), signup(c, ob, "b@x.com")
    la = mkloc(c, a)
    dev = pair(c, a, la)
    c.post("/edge/events", json=[ev(1)], headers=dev)
    c.post("/cameras", params={"location_id": la, "name": "c", "url": "rtsp://u:p@h/s"}, headers=a)
    # B must get 404 (not 403: don't confirm the id exists) on everything of A's
    for method, path, kw in [
        ("get", "/events", {"params": {"location_id": la}}),
        ("get", "/cameras", {"params": {"location_id": la}}),
        ("get", "/export/events.csv", {"params": {"location_id": la}}),
        ("post", "/pairing", {"params": {"location_id": la}}),
        ("post", "/cameras", {"params": {"location_id": la, "name": "x", "url": "rtsp://x"}}),
        ("patch", f"/locations/{la}/settings", {"params": {"staff_analytics": "on"}}),
        ("post", "/corrections", {"params": {"location_id": la, "kind": "k"}, "json": {}}),
    ]:
        r = getattr(c, method)(path, headers=b, **kw)
        assert r.status_code == 404, (path, r.status_code)
    assert c.get("/locations", headers=b).json() == []
    assert c.get("/devices", headers=b).json() == []
    assert c.get("/audit", headers=b).json() != c.get("/audit", headers=a).json()
    assert len(c.get("/events", params={"location_id": la}, headers=a).json()) == 1


def test_org_id_in_request_is_ignored(env):
    c, ob, _ = env
    a, b = signup(c, ob, "a@x.com"), signup(c, ob, "b@x.com")
    la = mkloc(c, a)
    r = c.get("/events", params={"location_id": la, "org_id": "whatever"}, headers=b)
    assert r.status_code == 404


def test_same_event_id_in_two_tenants_does_not_collide(env):
    c, ob, _ = env
    a, b = signup(c, ob, "a@x.com"), signup(c, ob, "b@x.com")
    la, lb = mkloc(c, a), mkloc(c, b)
    assert c.post("/edge/events", json=[ev(1)], headers=pair(c, a, la)).json()["accepted"] == 1
    assert c.post("/edge/events", json=[ev(1)], headers=pair(c, b, lb)).json()["accepted"] == 1


def test_device_token_cannot_read_user_api_and_vice_versa(env):
    c, ob, _ = env
    a = signup(c, ob, "a@x.com")
    dev = pair(c, a, mkloc(c, a))
    assert c.get("/locations", headers=dev).status_code == 401
    assert c.post("/edge/events", json=[ev(1)], headers=a).status_code == 401


def test_idempotent_replay(env):
    c, ob, _ = env
    a = signup(c, ob, "a@x.com")
    la = mkloc(c, a)
    dev = pair(c, a, la)
    batch = [ev(1), ev(2)]
    assert c.post("/edge/events", json=batch, headers=dev).json() == {"accepted": 2, "duplicates": 0}
    assert c.post("/edge/events", json=batch + [ev(3)], headers=dev).json() == {"accepted": 1, "duplicates": 2}


def test_pairing_code_single_use(env):
    c, ob, _ = env
    a = signup(c, ob, "a@x.com")
    code = c.post("/pairing", params={"location_id": mkloc(c, a)}, headers=a).json()["code"]
    assert c.post("/edge/pair", params={"code": code}).status_code == 200
    assert c.post("/edge/pair", params={"code": code}).status_code == 400


def test_camera_credentials_encrypted_at_rest_and_never_returned(env):
    c, ob, app = env
    a = signup(c, ob, "a@x.com")
    la = mkloc(c, a)
    c.post("/cameras", params={"location_id": la, "name": "c", "url": "rtsp://admin:s3cret@10.0.0.5/s"}, headers=a)
    raw = app.state.db.execute("SELECT url_enc FROM cameras").fetchone()[0]
    assert b"s3cret" not in raw
    assert "s3cret" not in c.get("/cameras", params={"location_id": la}, headers=a).text


def test_roles_and_no_escalation(env):
    c, ob, _ = env
    owner = signup(c, ob, "o@x.com")
    la = mkloc(c, owner)
    assert c.post("/invites", params={"email": "s@x.com", "role": "server", "location_id": la}, headers=owner).status_code == 200
    tok = [m for m in ob.sent if m["kind"] == "invite"][-1]["token"]
    assert c.post("/invites/accept", params={"token": tok, "password": PW}).status_code == 200
    server = {"Authorization": "Bearer " + c.post("/login", json={"email": "s@x.com", "password": PW}).json()["token"]}
    assert c.get("/export/events.csv", params={"location_id": la}, headers=server).status_code == 403
    assert c.post("/invites", params={"email": "z@x.com", "role": "owner"}, headers=server).status_code == 403
    assert c.post("/cameras", params={"location_id": la, "name": "x", "url": "rtsp://x"}, headers=server).status_code == 403
    # server sees only own section events
    dev = pair(c, owner, la)
    c.post("/edge/events", json=[ev(1, section="A"), ev(2, section="B")], headers=dev)
    assert c.get("/events", params={"location_id": la}, headers=server).json() == []


def test_location_scoped_role_cannot_see_other_location(env):
    c, ob, _ = env
    owner = signup(c, ob, "o@x.com")
    c.post("/billing/plan", params={"plan": "pro"}, headers=owner)
    l1, l2 = mkloc(c, owner, "L1"), mkloc(c, owner, "L2")
    c.post("/invites", params={"email": "g@x.com", "role": "gm", "location_id": l1}, headers=owner)
    tok = [m for m in ob.sent if m["kind"] == "invite"][-1]["token"]
    c.post("/invites/accept", params={"token": tok, "password": PW})
    gm = {"Authorization": "Bearer " + c.post("/login", json={"email": "g@x.com", "password": PW}).json()["token"]}
    assert c.get("/events", params={"location_id": l1}, headers=gm).status_code == 200
    assert c.get("/events", params={"location_id": l2}, headers=gm).status_code == 404
    assert [x["id"] for x in c.get("/locations", headers=gm).json()] == [l1]


def test_lockout_enumeration_and_unverified(env):
    c, ob, _ = env
    c.post("/signup", json={"email": "u@x.com", "password": PW, "org_name": "O"})
    assert c.post("/login", json={"email": "u@x.com", "password": PW}).status_code == 403
    signup_ok = signup(c, ob, "v@x.com")
    assert signup_ok
    codes = {c.post("/login", json={"email": "ghost@x.com", "password": "bad-password-1"}).status_code,
             c.post("/login", json={"email": "v@x.com", "password": "bad-password-1"}).status_code}
    assert codes == {401}


def test_account_locks_after_failures():
    ob = Outbox()
    c = TestClient(create_app(outbox=ob))
    signup(c, ob, "l@x.com")
    for _ in range(5):
        assert c.post("/login", json={"email": "l@x.com", "password": "wrong-password"}).status_code == 401
    assert c.post("/login", json={"email": "l@x.com", "password": PW}).status_code == 423


def test_2fa_flow(env):
    c, ob, _ = env
    a = signup(c, ob, "t@x.com")
    sec = c.post("/2fa/setup", headers=a).json()["secret"]
    assert c.post("/login", json={"email": "t@x.com", "password": PW}).status_code == 401
    r = c.post("/login", json={"email": "t@x.com", "password": PW, "totp": security.totp(sec)})
    assert r.status_code == 200


def test_password_reset_kills_sessions_and_does_not_enumerate(env):
    c, ob, _ = env
    a = signup(c, ob, "r@x.com")
    assert c.post("/password-reset/request", params={"email": "nobody@x.com"}).json() == {"ok": True}
    c.post("/password-reset/request", params={"email": "r@x.com"})
    tok = [m for m in ob.sent if m["kind"] == "password_reset"][-1]["token"]
    assert c.post("/password-reset/confirm", params={"token": tok, "new_password": "brand-new-password"}).status_code == 200
    assert c.get("/locations", headers=a).status_code == 401
    assert c.post("/login", json={"email": "r@x.com", "password": "brand-new-password"}).status_code == 200


def test_plan_limits_and_retention(env):
    c, ob, _ = env
    a = signup(c, ob, "p@x.com")
    mkloc(c, a)
    assert c.post("/locations", params={"name": "L2"}, headers=a).status_code == 402
    la = c.get("/locations", headers=a).json()[0]["id"]
    assert c.patch(f"/locations/{la}/settings", params={"retention_days": 90}, headers=a).status_code == 402
    assert c.patch(f"/locations/{la}/settings", params={"retention_days": 5}, headers=a).status_code == 200


def test_staff_analytics_off_blocks_endpoint_and_audit_records_export(env):
    c, ob, _ = env
    a = signup(c, ob, "s@x.com")
    la = mkloc(c, a)
    assert c.get("/analytics/staff-greet-times", params={"location_id": la}, headers=a).status_code == 200
    c.patch(f"/locations/{la}/settings", params={"staff_analytics": "off"}, headers=a)
    assert c.get("/analytics/staff-greet-times", params={"location_id": la}, headers=a).status_code == 403
    c.get("/export/events.csv", params={"location_id": la}, headers=a)
    assert "export" in {x["action"] for x in c.get("/audit", headers=a).json()}


def test_data_deletion(env):
    c, ob, _ = env
    a = signup(c, ob, "d@x.com")
    la = mkloc(c, a)
    c.post("/edge/events", json=[ev(1)], headers=pair(c, a, la))
    assert c.delete("/org/data", params={"confirm": "no"}, headers=a).status_code == 422
    assert c.delete("/org/data", params={"confirm": "DELETE"}, headers=a).status_code == 200
    assert c.get("/locations", headers=a).json() == []


def test_security_primitives():
    assert security.verify_password("pw", security.hash_password("pw"))
    assert not security.verify_password("px", security.hash_password("pw"))
    assert security.totp("JBSWY3DPEHPK3PXP", at=59) == security.totp("JBSWY3DPEHPK3PXP", at=59)
    rl = security.RateLimiter(2, 10)
    assert rl.allow("k", 0) and rl.allow("k", 1) and not rl.allow("k", 2) and rl.allow("k", 20)
