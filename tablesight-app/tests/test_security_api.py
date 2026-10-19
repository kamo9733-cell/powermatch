"""Adversarial tests: IDOR, privilege escalation, input validation, headers, audit, SQLi, CSV injection."""
import csv
import io
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tablesight.platform.app import Outbox, create_app
from tablesight.platform.security import csv_safe

PW = "correct-horse-battery"


class Clock:
    def __init__(self, t=1_800_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


@pytest.fixture
def env():
    ob, clk = Outbox(), Clock()
    app = create_app(outbox=ob, clock=clk)
    return TestClient(app), ob, app, clk


def signup(c, ob, email):
    c.post("/signup", json={"email": email, "password": PW, "org_name": "Org"}).raise_for_status()
    tok = [m for m in ob.sent if m["to"] == email and m["kind"] == "verify_email"][-1]["token"]
    c.post("/verify-email", params={"token": tok}).raise_for_status()
    return auth(c, email)


def auth(c, email):
    r = c.post("/login", json={"email": email, "password": PW})
    r.raise_for_status()
    return {"Authorization": "Bearer " + r.json()["token"]}


def invite(c, ob, h, email, role, lid=None, **kw):
    p = {"email": email, "role": role, **({"location_id": lid} if lid else {}), **kw}
    r = c.post("/invites", params=p, headers=h)
    if r.status_code != 200:
        return r
    tok = [m for m in ob.sent if m["kind"] == "invite" and m["to"] == email][-1]["token"]
    c.post("/invites/accept", json={"token": tok, "password": PW}).raise_for_status()
    return auth(c, email)


def pair(c, h, lid):
    code = c.post("/pairing", params={"location_id": lid}, headers=h).json()["code"]
    r = c.post("/edge/pair", params={"code": code}).json()
    return {"Authorization": "Bearer " + r["token"]}, r["device_id"]


def mkloc(c, h, name="L1"):
    return c.post("/locations", params={"name": name}, headers=h).json()["id"]


def ev(i, **kw):
    return {"event_id": f"e{i}", "t": 1_800_000_000.0 + i, "table_id": "T1", "kind": "seated",
            "detail": {}, **kw}


def actions(c, h):
    return [a["action"] for a in c.get("/audit", headers=h).json()]


# ---- headers / transport hardening ------------------------------------------------------------
def test_security_headers_on_every_response_and_no_store_on_auth(env):
    c, ob, *_ = env
    h = signup(c, ob, "a@x.com")
    for r in (c.get("/locations", headers=h), c.post("/login", json={"email": "a@x.com", "password": "x" * 12}),
              c.get("/locations"), c.get("/nope"), c.post("/signup", json={})):
        hd = r.headers
        assert hd["x-content-type-options"] == "nosniff"
        assert hd["x-frame-options"] == "DENY"
        assert "frame-ancestors 'none'" in hd["content-security-policy"]
        assert "default-src 'none'" in hd["content-security-policy"]
        assert hd["referrer-policy"] == "no-referrer"
        assert "no-store" in hd["cache-control"]
        assert "max-age" in hd["strict-transport-security"]


def test_interactive_docs_disabled_by_default(env):
    c, *_ = env
    assert c.get("/docs").status_code == 404 and c.get("/redoc").status_code == 404


def test_oversized_bodies_are_rejected_before_parsing(env):
    c, ob, *_ = env
    h = signup(c, ob, "a@x.com")
    r = c.post("/corrections", params={"location_id": "x", "kind": "k"}, headers=h, content=b"{" + b" " * (5 * 2**20) + b"}")
    assert r.status_code == 413


# ---- input validation -------------------------------------------------------------------------
def test_event_validation_limits(env):
    c, ob, _, clk = env
    h = signup(c, ob, "a@x.com")
    lid = mkloc(c, h)
    dev, _ = pair(c, h, lid)
    post = lambda body: c.post("/edge/events", json=body, headers=dev)
    assert post([ev(1)]).json() == {"accepted": 1, "duplicates": 0}
    r = post([ev(2, t=clk.t + 86_400), ev(3), ev(4, t=-5)]).json()
    assert r["accepted"] == 1 and r["rejected"] == 2  # future / negative timestamps never stored
    assert post([ev(5, event_id="x" * 500)]).status_code == 422
    assert post([ev(6, kind="a" * 200)]).status_code == 422
    assert post([ev(7, table_id="a" * 200)]).status_code == 422
    assert post([ev(8, detail={"blob": "z" * 10_000})]).status_code == 422
    assert post([ev(9, detail={"a": {"b": {"c": {"d": {"e": {"f": 1}}}}}})]).status_code == 422
    assert c.post("/edge/events", content=b'[{"event_id":"n","t":NaN,"table_id":"T","kind":"k"}]',
                  headers={**dev, "content-type": "application/json"}).status_code == 422
    assert post([ev(i) for i in range(1001)]).status_code == 413
    assert len(c.get("/events", params={"location_id": lid}, headers=h).json()) == 2


def test_events_list_is_paginated_and_bounded(env):
    c, ob, *_ = env
    h = signup(c, ob, "a@x.com")
    lid = mkloc(c, h)
    dev, _ = pair(c, h, lid)
    c.post("/edge/events", json=[ev(i) for i in range(30)], headers=dev)
    assert len(c.get("/events", params={"location_id": lid, "limit": 10}, headers=h).json()) == 10
    assert c.get("/events", params={"location_id": lid, "limit": 10**9}, headers=h).status_code == 422


def test_heartbeat_limits_and_clock_skew_flag(env):
    c, ob, _, clk = env
    h = signup(c, ob, "a@x.com")
    dev, _ = pair(c, h, mkloc(c, h))
    assert c.post("/edge/heartbeat", json={"k": "v" * 100_000}, headers=dev).status_code in (413, 422)
    assert c.post("/edge/heartbeat", params={"version": "v" * 500}, json={}, headers=dev).status_code == 422
    assert c.post("/edge/heartbeat", params={"device_t": clk.t - 900}, json={}, headers=dev).status_code == 200
    (d,) = c.get("/devices", headers=h).json()
    assert '"clock_skew_s"' in d["health"]


def test_camera_and_location_input_validation(env):
    c, ob, *_ = env
    h = signup(c, ob, "a@x.com")
    lid = mkloc(c, h)
    base = {"location_id": lid, "name": "c"}
    for bad in ("file:///etc/passwd", "javascript:alert(1)", "gopher://x", "rtsp://" + "a" * 3000, ""):
        assert c.post("/cameras", params={**base, "url": bad}, headers=h).status_code == 422, bad
    assert c.post("/cameras", params={**base, "url": "rtsp://u:p@10.0.0.5/s"}, headers=h).status_code == 200
    assert c.post("/cameras", params={**base, "name": "n" * 500, "url": "rtsp://x/s"}, headers=h).status_code == 422
    assert c.post("/locations", params={"name": "x" * 500}, headers=h).status_code == 422
    assert c.post("/locations", params={"name": "ok", "tz": "Not/AZone"}, headers=h).status_code in (402, 422)
    assert c.post("/locations", params={"name": "ok", "venue_type": "<script>"}, headers=h).status_code in (402, 422)


def test_correction_payload_is_bounded(env):
    c, ob, *_ = env
    h = signup(c, ob, "a@x.com")
    lid = mkloc(c, h)
    ok = c.post("/corrections", params={"location_id": lid, "kind": "waiter"}, json={"table": "T1"}, headers=h)
    assert ok.status_code == 200
    big = c.post("/corrections", params={"location_id": lid, "kind": "waiter"}, json={"x": "y" * 50_000}, headers=h)
    assert big.status_code == 422
    assert c.post("/corrections", params={"location_id": lid, "kind": "k" * 300}, json={}, headers=h).status_code == 422


# ---- injection --------------------------------------------------------------------------------
def test_csv_export_neutralises_formula_injection(env):
    c, ob, *_ = env
    h = signup(c, ob, "a@x.com")
    lid = mkloc(c, h)
    dev, _ = pair(c, h, lid)
    evil = ["=HYPERLINK(\"http://evil\",\"x\")", "+1+1", "-2+3", "@SUM(A1)"]
    for p in ("\tcmd", "\rcmd", "=x"):
        assert csv_safe(p)[:1] == "'"
    c.post("/edge/events", json=[ev(i, event_id=f"id{i}", table_id=p) for i, p in enumerate(evil)], headers=dev)
    r = c.get("/export/events.csv", params={"location_id": lid}, headers=h)
    assert r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers["content-disposition"]
    rows = list(csv.reader(io.StringIO(r.text)))[1:]
    assert len(rows) == len(evil)
    for row in rows:
        for cell in row:
            assert cell[:1] not in ("=", "+", "-", "@", "\t", "\r"), cell
        assert row[1][:1].isdigit()  # numeric timestamp column is untouched


def test_sql_injection_strings_are_inert(env):
    c, ob, app, _ = env
    h = signup(c, ob, "a@x.com")
    lid = mkloc(c, h)
    for payload in ("' OR '1'='1", "x'; DROP TABLE events;--", "1 UNION SELECT url_enc FROM cameras"):
        assert c.get("/events", params={"location_id": payload}, headers=h).status_code == 404
        assert c.post("/login", json={"email": payload + "@x.com", "password": "x" * 12}).status_code in (401, 422)
        assert c.get("/cameras", params={"location_id": payload}, headers=h).status_code == 404
        assert c.patch(f"/locations/{payload}/settings", params={"staff_analytics": "on"}, headers=h).status_code == 404
    assert c.get("/events", params={"location_id": lid}, headers=h).status_code == 200
    assert app.state.db.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0


def test_no_dynamic_sql_in_platform_source():
    """Every execute() takes a literal; values travel as parameters. Table names are never interpolated."""
    src = Path(__file__).parents[1] / "tablesight" / "platform" / "app.py"
    bad = re.findall(r"execute\(\s*(?:f[\"']|[\"'][^\"']*[\"']\s*(?:%|\+|\.format))", src.read_text())
    assert bad == []
    assert "{t}" not in src.read_text()


# ---- IDOR / privilege escalation --------------------------------------------------------------
def test_gm_cannot_see_devices_or_pair_for_other_locations(env):
    c, ob, *_ = env
    owner = signup(c, ob, "o@x.com")
    c.post("/billing/plan", params={"plan": "pro"}, headers=owner)
    l1, l2 = mkloc(c, owner, "L1"), mkloc(c, owner, "L2")
    pair(c, owner, l1)
    pair(c, owner, l2)
    gm = invite(c, ob, owner, "g@x.com", "gm", l1)
    seen = c.get("/devices", headers=gm).json()
    assert [d["location_id"] for d in seen] == [l1]
    assert c.post("/pairing", params={"location_id": l2}, headers=gm).status_code == 404


def test_invite_escalation_matrix(env):
    c, ob, *_ = env
    owner = signup(c, ob, "o@x.com")
    c.post("/billing/plan", params={"plan": "pro"}, headers=owner)
    l1, l2 = mkloc(c, owner, "L1"), mkloc(c, owner, "L2")
    gm = invite(c, ob, owner, "g@x.com", "gm", l1)
    assert c.post("/invites", params={"email": "x@x.com", "role": "gm", "location_id": l1}, headers=gm).status_code == 403
    assert c.post("/invites", params={"email": "x@x.com", "role": "owner"}, headers=gm).status_code == 403
    assert c.post("/invites", params={"email": "x@x.com", "role": "area_manager"}, headers=gm).status_code == 403
    assert c.post("/invites", params={"email": "x@x.com", "role": "host", "location_id": l2}, headers=gm).status_code == 404
    assert c.post("/invites", params={"email": "x@x.com", "role": "superadmin"}, headers=owner).status_code in (403, 422)
    assert c.post("/invites", params={"email": "x@x.com", "role": "owner"}, headers=owner).status_code == 403
    host = invite(c, ob, gm, "h@x.com", "host", l1)
    assert c.post("/invites", params={"email": "y@x.com", "role": "viewer", "location_id": l1}, headers=host).status_code == 403


def test_org_level_invite_does_not_store_a_foreign_location(env):
    c, ob, app, _ = env
    a, b = signup(c, ob, "a@x.com"), signup(c, ob, "b@x.com")
    lb = mkloc(c, b)
    invite(c, ob, a, "am@x.com", "area_manager", lb)
    row = app.state.db.execute("SELECT location_id FROM memberships m JOIN users u ON u.id=m.user_id WHERE u.email='am@x.com'").fetchone()
    assert row["location_id"] is None


def test_invite_dies_when_inviter_loses_access_or_authority(env):
    c, ob, *_ = env
    owner = signup(c, ob, "o@x.com")
    lid = mkloc(c, owner)
    gm = invite(c, ob, owner, "g@x.com", "gm", lid)
    c.post("/invites", params={"email": "late@x.com", "role": "host", "location_id": lid}, headers=gm)
    tok = [m for m in ob.sent if m["kind"] == "invite" and m["to"] == "late@x.com"][-1]["token"]
    gm_id = next(m for m in c.get("/members", headers=owner).json() if m["email"] == "g@x.com")["user_id"]
    assert c.delete(f"/members/{gm_id}", headers=owner).status_code == 200
    assert c.post("/invites/accept", json={"token": tok, "password": PW}).status_code == 400
    assert c.get("/locations", headers=gm).status_code == 401  # removed member's sessions die at once


def test_accepting_an_invite_never_downgrades_an_existing_member(env):
    c, ob, *_ = env
    owner = signup(c, ob, "o@x.com")
    lid = mkloc(c, owner)
    gm = invite(c, ob, owner, "g@x.com", "gm", lid)
    c.post("/invites", params={"email": "o@x.com", "role": "viewer", "location_id": lid}, headers=gm)
    tok = [m for m in ob.sent if m["kind"] == "invite" and m["to"] == "o@x.com"][-1]["token"]
    assert c.post("/invites/accept", json={"token": tok}).status_code == 409
    assert c.post("/billing/plan", params={"plan": "trial"}, headers=owner).status_code == 200  # still owner


def test_member_management_is_rank_and_scope_checked_and_audited(env):
    c, ob, *_ = env
    owner = signup(c, ob, "o@x.com")
    c.post("/billing/plan", params={"plan": "pro"}, headers=owner)
    l1, l2 = mkloc(c, owner, "L1"), mkloc(c, owner, "L2")
    gm1 = invite(c, ob, owner, "g1@x.com", "gm", l1)
    invite(c, ob, owner, "g2@x.com", "gm", l2)
    invite(c, ob, gm1, "h@x.com", "host", l1)
    invite(c, ob, owner, "h2@x.com", "host", l2)
    members = {m["email"]: m for m in c.get("/members", headers=gm1).json()}
    assert set(members) == {"g1@x.com", "h@x.com"}  # a gm sees only their own location
    host_id, g1_id = members["h@x.com"]["user_id"], members["g1@x.com"]["user_id"]
    h2_id = next(m["user_id"] for m in c.get("/members", headers=owner).json() if m["email"] == "h2@x.com")
    me_owner = next(m["user_id"] for m in c.get("/members", headers=owner).json() if m["email"] == "o@x.com")
    # escalation attempts
    assert c.patch(f"/members/{host_id}", params={"role": "gm"}, headers=gm1).status_code == 403
    assert c.patch(f"/members/{g1_id}", params={"role": "viewer"}, headers=gm1).status_code == 403  # self
    assert c.patch(f"/members/{h2_id}", params={"role": "viewer"}, headers=gm1).status_code == 404  # other location
    assert c.patch(f"/members/{me_owner}", params={"role": "viewer"}, headers=gm1).status_code in (403, 404)
    assert c.patch(f"/members/{me_owner}", params={"role": "viewer"}, headers=owner).status_code == 403
    assert c.delete(f"/members/{me_owner}", headers=owner).status_code == 403  # never orphan an org
    assert c.patch(f"/members/{host_id}", params={"role": "nonsense"}, headers=gm1).status_code in (403, 422)
    # legit change takes effect and is audited
    assert c.patch(f"/members/{host_id}", params={"role": "viewer"}, headers=gm1).status_code == 200
    assert next(m for m in c.get("/members", headers=gm1).json() if m["user_id"] == host_id)["role"] == "viewer"
    assert c.delete(f"/members/{host_id}", headers=gm1).status_code == 200
    log = actions(c, owner)
    assert "member.role_change" in log and "member.remove" in log and "invite.accept" in log


def test_device_revocation_is_tenant_and_scope_checked(env):
    c, ob, *_ = env
    a, b = signup(c, ob, "a@x.com"), signup(c, ob, "b@x.com")
    dev, did = pair(c, a, mkloc(c, a))
    assert c.delete(f"/devices/{did}", headers=b).status_code == 404
    assert c.post("/edge/events", json=[ev(1)], headers=dev).status_code == 200
    assert c.delete(f"/devices/{did}", headers=a).status_code == 200
    assert c.post("/edge/events", json=[ev(2)], headers=dev).status_code == 401  # stolen token is dead
    assert "device.revoke" in actions(c, a)


def test_server_role_sees_only_own_section_and_cannot_export(env):
    c, ob, *_ = env
    owner = signup(c, ob, "o@x.com")
    lid = mkloc(c, owner)
    server = invite(c, ob, owner, "s@x.com", "server", lid, section="A")
    dev, _ = pair(c, owner, lid)
    c.post("/edge/events", json=[ev(1, detail={"section": "A"}), ev(2, detail={"section": "B"}), ev(3)], headers=dev)
    got = c.get("/events", params={"location_id": lid}, headers=server).json()
    assert [e["event_id"] for e in got] == ["e1"]
    assert c.get("/export/events.csv", params={"location_id": lid}, headers=server).status_code == 403


def test_self_serve_plan_upgrade_can_be_disabled_for_production():
    ob = Outbox()
    c = TestClient(create_app(outbox=ob, allow_self_serve_plan=False))
    h = signup(c, ob, "o@x.com")
    assert c.post("/billing/plan", params={"plan": "enterprise"}, headers=h).status_code == 402
    assert c.post("/billing/plan", params={"plan": "pro"}, headers=h).status_code == 402
    assert c.post("/billing/plan", params={"plan": "trial"}, headers=h).status_code == 200  # downgrade is fine


# ---- audit completeness -----------------------------------------------------------------------
def test_audit_covers_account_security_events(env):
    c, ob, _, clk = env
    h = signup(c, ob, "o@x.com")
    other = auth(c, "o@x.com")
    sid = next(s["id"] for s in c.get("/sessions", headers=h).json() if not s["current"])
    c.delete(f"/sessions/{sid}", headers=h)
    c.post("/2fa/setup", headers=h)
    c.post("/logout-all", headers=h)
    assert c.get("/audit", headers=other).status_code == 401
    c.post("/password-reset/request", params={"email": "o@x.com"})
    tok = [m for m in ob.sent if m["kind"] == "password_reset"][-1]["token"]
    c.post("/password-reset/confirm", json={"token": tok, "new_password": "a-brand-new-password"})
    from tablesight.platform import security
    sec = c.app.state.db.execute("SELECT totp_secret FROM users").fetchone()[0]
    r = c.post("/login", json={"email": "o@x.com", "password": "a-brand-new-password", "totp": security.totp(sec, clk.t)})
    assert r.status_code == 200  # 2FA survives a password reset
    log = actions(c, {"Authorization": "Bearer " + r.json()["token"]})
    for a in ("session.revoke", "2fa.setup", "logout_all", "password.reset_request", "password.reset"):
        assert a in log, a


def test_audit_log_records_login_logout_feed_access_and_ip(env):
    c, ob, app, clk = env
    h = signup(c, ob, "o@x.com")
    lid = mkloc(c, h)
    c.get("/events", params={"location_id": lid}, headers=h)
    clk.t += 120
    c.get("/events", params={"location_id": lid}, headers=h)  # second read after the dedupe window
    c.get("/analytics/staff-greet-times", params={"location_id": lid}, headers=h)
    c.get("/export/events.csv", params={"location_id": lid}, headers=h)
    c.post("/corrections", params={"location_id": lid, "kind": "k"}, json={}, headers=h)
    pair(c, h, lid)
    c.post("/billing/plan", params={"plan": "starter"}, headers=h)
    c.post("/logout", headers=h)
    h = auth(c, "o@x.com")
    sid = next(s["id"] for s in c.get("/sessions", headers=h).json())
    log = actions(c, h)
    for a in ("login", "logout", "events.read", "staff_analytics.read", "export", "correction.create",
              "pairing.create", "device.pair", "billing.plan", "location.create"):
        assert a in log, a
    assert log.count("events.read") == 2
    assert app.state.db.execute("SELECT COUNT(*) FROM audit WHERE ip IS NULL OR ip=''").fetchone()[0] == 0
    assert sid


def test_audit_survives_org_data_deletion_and_is_tenant_scoped(env):
    c, ob, *_ = env
    a, b = signup(c, ob, "a@x.com"), signup(c, ob, "b@x.com")
    c.delete("/org/data", params={"confirm": "DELETE"}, headers=a)
    assert "org.data_deleted" in actions(c, a)
    assert "org.data_deleted" not in actions(c, b)


def test_deeply_nested_json_is_a_400_not_a_crash(env):
    c, ob, *_ = env
    h = signup(c, ob, "a@x.com")
    bomb = b"[" * 200_000 + b"]" * 200_000
    r = c.post("/corrections", params={"location_id": "x", "kind": "k"}, headers={**h, "content-type": "application/json"}, content=bomb)
    assert r.status_code in (400, 422)
    assert c.get("/locations", headers=h).status_code == 200  # server still healthy


def test_file_database_is_owner_only_and_old_schemas_are_migrated(tmp_path):
    import sqlite3
    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.executescript("CREATE TABLE sessions(token_hash TEXT PRIMARY KEY, user_id TEXT, org_id TEXT, expires REAL);"
                      "CREATE TABLE invites(token_hash TEXT PRIMARY KEY, org_id TEXT, email TEXT, role TEXT,"
                      " location_id TEXT, expires REAL);")
    old.commit()
    old.close()
    ob = Outbox()
    c = TestClient(create_app(str(path), outbox=ob))
    h = signup(c, ob, "a@x.com")
    assert c.get("/sessions", headers=h).status_code == 200
    assert (path.stat().st_mode & 0o077) == 0
