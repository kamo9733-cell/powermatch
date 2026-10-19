"""Adversarial tests: authentication, sessions, tokens, rate limits, concurrency (docs/SECURITY_REVIEW.md)."""
import threading

from fastapi.testclient import TestClient

from tablesight.platform import security
from tablesight.platform.app import Outbox, create_app

PW = "correct-horse-battery"


class Clock:
    def __init__(self, t=1_800_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


def make(**kw):
    ob = Outbox()
    clk = kw.pop("clock", None) or Clock()
    app = create_app(outbox=ob, clock=clk, **kw)
    return TestClient(app), ob, app, clk


def signup(c, ob, email, org="Org"):
    c.post("/signup", json={"email": email, "password": PW, "org_name": org}).raise_for_status()
    tok = [m for m in ob.sent if m["to"] == email and m["kind"] == "verify_email"][-1]["token"]
    c.post("/verify-email", params={"token": tok}).raise_for_status()
    r = c.post("/login", json={"email": email, "password": PW})
    r.raise_for_status()
    return {"Authorization": "Bearer " + r.json()["token"]}


def mkloc(c, h, name="L1"):
    return c.post("/locations", params={"name": name}, headers=h).json()["id"]


def login(c, email, password=PW, **extra):
    return c.post("/login", json={"email": email, "password": password, **extra})


# ---- enumeration / timing ---------------------------------------------------------------------
def test_login_does_identical_password_work_for_unknown_and_known_user(monkeypatch):
    c, ob, _, _ = make()
    signup(c, ob, "known@x.com")
    calls = {"verify": 0, "hash": 0}
    real_v, real_h = security.verify_password, security.hash_password

    def v(*a):
        calls["verify"] += 1
        return real_v(*a)

    def h(*a):
        calls["hash"] += 1
        return real_h(*a)

    monkeypatch.setattr(security, "verify_password", v)
    monkeypatch.setattr(security, "hash_password", h)
    login(c, "ghost@x.com", "bad-password-1")
    unknown = dict(calls)
    calls.update(verify=0, hash=0)
    login(c, "known@x.com", "bad-password-1")
    assert unknown == calls == {"verify": 1, "hash": 0}


def test_lockout_applies_identically_to_unknown_emails():
    c, ob, _, _ = make()
    signup(c, ob, "real@x.com")
    for e in ("ghost@x.com", "real@x.com"):
        for _ in range(5):
            assert login(c, e, "bad-password-1").status_code == 401
        assert login(c, e, PW).status_code == 423  # real user: even the right password; ghost: same code


def test_duplicate_signup_does_not_reveal_registration():
    c, ob, _, _ = make()
    first = c.post("/signup", json={"email": "d@x.com", "password": PW, "org_name": "O"})
    second = c.post("/signup", json={"email": "D@x.com", "password": PW, "org_name": "O"})
    assert first.status_code == second.status_code == 200
    assert set(first.json()) == set(second.json())
    assert [m["kind"] for m in ob.sent if m["to"].lower() == "d@x.com"].count("verify_email") == 1


def test_validation_errors_never_echo_secrets():
    c, *_ = make()
    r = c.post("/signup", json={"email": "e@x.com", "password": "short-pw", "org_name": "O"})
    assert r.status_code == 422 and "short-pw" not in r.text
    r = c.post("/login", json={"email": "e@x.com", "password": "p" * 5000})
    assert r.status_code == 422 and "ppppp" not in r.text


def test_password_and_email_size_limits():
    c, *_ = make()
    assert c.post("/signup", json={"email": "a@x.com", "password": "p" * 10_000, "org_name": "O"}).status_code == 422
    assert c.post("/signup", json={"email": "not-an-email", "password": PW, "org_name": "O"}).status_code == 422
    assert c.post("/signup", json={"email": "a" * 300 + "@x.com", "password": PW, "org_name": "O"}).status_code == 422
    assert c.post("/signup", json={"email": "a@x.com", "password": PW, "org_name": "O" * 500}).status_code == 422


# ---- rate limits ------------------------------------------------------------------------------
def test_per_ip_login_limit_spans_emails_and_ignores_spoofed_forwarded_for():
    c, *_ = make()
    codes = [login(c, f"user{i}@x.com", "bad-password-1").status_code
             for i in range(60)]
    assert 429 in codes and codes.index(429) <= 35
    spoof = c.post("/login", json={"email": "other@x.com", "password": "bad-password-1"},
                   headers={"X-Forwarded-For": "9.9.9.9"})
    assert spoof.status_code == 429


def test_per_ip_signup_limit():
    c, *_ = make()
    codes = [c.post("/signup", json={"email": f"s{i}@x.com", "password": PW, "org_name": "O"}).status_code
             for i in range(40)]
    assert 429 in codes


def test_reset_request_per_email_cap_is_silent_and_per_ip_cap_is_enforced():
    c, ob, _, clk = make()
    signup(c, ob, "r@x.com")
    for _ in range(8):
        assert c.post("/password-reset/request", params={"email": "r@x.com"}).json() == {"ok": True}
    assert len([m for m in ob.sent if m["kind"] == "password_reset"]) <= 3  # no mail-bombing a victim
    codes = [c.post("/password-reset/request", params={"email": f"x{i}@x.com"}).status_code for i in range(60)]
    assert 429 in codes


def test_pairing_code_brute_force_is_throttled_then_recovers():
    c, ob, _, clk = make()
    h = signup(c, ob, "p@x.com")
    code = c.post("/pairing", params={"location_id": mkloc(c, h)}, headers=h).json()["code"]
    seen = [c.post("/edge/pair", params={"code": f"AAAAA-{i:05d}"[:11]}).status_code for i in range(25)]
    assert 429 in seen
    assert c.post("/edge/pair", params={"code": code}).status_code == 429  # even the real one, from this IP
    clk.t += 400  # failure window (300s) over, code (900s) still alive
    assert c.post("/edge/pair", params={"code": code}).status_code == 200


def test_pairing_code_entropy_and_format():
    c, ob, _, _ = make()
    h = signup(c, ob, "p@x.com")
    lid = mkloc(c, h)
    codes = set()
    for _ in range(5):
        codes.add(c.post("/pairing", params={"location_id": lid}, headers=h).json()["code"])
    assert len(codes) == 5
    for code in codes:
        raw = code.replace("-", "")
        assert len(raw) >= 10 and set(raw) <= set(security.CODE_ALPHABET)
    assert len(security.CODE_ALPHABET) ** 10 > 2 ** 48


def test_pairing_codes_outstanding_are_capped_and_pairing_accepts_lowercase():
    c, ob, _, _ = make()
    h = signup(c, ob, "p@x.com")
    lid = mkloc(c, h)
    rs = [c.post("/pairing", params={"location_id": lid}, headers=h) for _ in range(15)]
    assert rs[-1].status_code == 429
    assert c.post("/edge/pair", params={"code": rs[0].json()["code"].lower()}).status_code == 200


# ---- sessions ---------------------------------------------------------------------------------
def test_session_absolute_and_idle_expiry():
    c, ob, _, clk = make()
    h = signup(c, ob, "s@x.com")
    for _ in range(3):  # steady activity every 3h keeps the idle timer fresh...
        clk.t += 3 * 3600
        assert c.get("/locations", headers=h).status_code == 200
    clk.t += 3.5 * 3600  # ...but the 12h absolute cap (now 12.5h) still ends the session
    assert c.get("/locations", headers=h).status_code == 401
    h2 = {"Authorization": "Bearer " + login(c, "s@x.com").json()["token"]}
    clk.t += 5 * 3600  # well inside 12h, but idle longer than the idle limit
    assert c.get("/locations", headers=h2).status_code == 401


def test_logout_all_and_session_list_and_revoke():
    c, ob, _, _ = make()
    h1 = signup(c, ob, "u@x.com")
    h2 = {"Authorization": "Bearer " + login(c, "u@x.com").json()["token"]}
    h3 = {"Authorization": "Bearer " + login(c, "u@x.com").json()["token"]}
    lst = c.get("/sessions", headers=h1).json()
    assert len(lst) == 3 and sum(s["current"] for s in lst) == 1
    assert all("token" not in s and "token_hash" not in s for s in lst)
    other = next(s for s in lst if not s["current"])
    assert c.delete(f"/sessions/{other['id']}", headers=h1).status_code == 200
    assert len(c.get("/sessions", headers=h1).json()) == 2
    assert c.post("/logout-all", headers=h1).status_code == 200
    for h in (h1, h2, h3):
        assert c.get("/locations", headers=h).status_code == 401


def test_cannot_list_or_revoke_another_users_sessions():
    c, ob, _, _ = make()
    a, b = signup(c, ob, "a@x.com"), signup(c, ob, "b@x.com")
    sid = c.get("/sessions", headers=a).json()[0]["id"]
    assert c.delete(f"/sessions/{sid}", headers=b).status_code == 404
    assert c.get("/locations", headers=a).status_code == 200
    assert sid not in [s["id"] for s in c.get("/sessions", headers=b).json()]
    c.post("/logout-all", headers=b)
    assert c.get("/locations", headers=a).status_code == 200  # b's logout-all never touches a


def test_authorization_scheme_must_be_bearer():
    c, ob, _, _ = make()
    h = signup(c, ob, "a@x.com")
    raw = h["Authorization"].removeprefix("Bearer ")
    assert c.get("/locations", headers={"Authorization": raw}).status_code == 401
    assert c.get("/locations", headers={"Authorization": "Basic " + raw}).status_code == 401
    assert c.get("/locations", headers={"Authorization": "bearer " + raw}).status_code == 200


def test_sessions_per_user_are_capped():
    c, ob, _, _ = make()
    signup(c, ob, "cap@x.com")
    for _ in range(25):
        login(c, "cap@x.com")
        c.app.state.clock.t += 10  # stay under the per-email rate limit window
    h = {"Authorization": "Bearer " + login(c, "cap@x.com").json()["token"]}
    assert len(c.get("/sessions", headers=h).json()) <= 20


# ---- 2FA --------------------------------------------------------------------------------------
def test_totp_code_cannot_be_replayed_and_failures_lock():
    c, ob, _, clk = make()
    a = signup(c, ob, "t@x.com")
    sec = c.post("/2fa/setup", headers=a).json()["secret"]
    code = security.totp(sec, clk.t)
    assert login(c, "t@x.com", totp=code).status_code == 200
    assert login(c, "t@x.com", totp=code).status_code == 401  # same code, same window
    codes = [login(c, "t@x.com", totp="000000").status_code for _ in range(5)]
    assert 423 in codes  # wrong 2FA codes feed the same lockout as wrong passwords
    assert login(c, "t@x.com", totp=security.totp(sec, clk.t + 30)).status_code == 423


def test_stolen_session_cannot_replace_existing_2fa_secret():
    c, ob, _, clk = make()
    a = signup(c, ob, "t@x.com")
    sec = c.post("/2fa/setup", headers=a).json()["secret"]
    tok = {"Authorization": "Bearer " + login(c, "t@x.com", totp=security.totp(sec, clk.t)).json()["token"]}
    assert c.post("/2fa/setup", headers=tok).status_code in (401, 403, 409)
    clk.t += 60
    assert c.post("/2fa/setup", params={"current_totp": security.totp(sec, clk.t)}, headers=tok).status_code == 200


# ---- token reuse ------------------------------------------------------------------------------
def test_verification_and_reset_tokens_are_single_use_and_superseded():
    c, ob, _, _ = make()
    signup(c, ob, "r@x.com")
    vtok = [m for m in ob.sent if m["kind"] == "verify_email"][-1]["token"]
    assert c.post("/verify-email", params={"token": vtok}).status_code == 400  # already consumed
    c.post("/password-reset/request", params={"email": "r@x.com"})
    first = [m for m in ob.sent if m["kind"] == "password_reset"][-1]["token"]
    c.app.state.clock.t += 400  # past the per-email spacing window, inside the hour cap
    c.post("/password-reset/request", params={"email": "r@x.com"})
    second = [m for m in ob.sent if m["kind"] == "password_reset"][-1]["token"]
    assert first != second
    assert c.post("/password-reset/confirm", params={"token": first, "new_password": "new-password-1"}).status_code == 400
    assert c.post("/password-reset/confirm", json={"token": second, "new_password": "new-password-1"}).status_code == 200
    assert c.post("/password-reset/confirm", params={"token": second, "new_password": "new-password-2"}).status_code == 400


def test_reset_confirm_accepts_body_so_secrets_need_not_be_in_urls():
    c, ob, _, _ = make()
    signup(c, ob, "r@x.com")
    c.post("/password-reset/request", params={"email": "r@x.com"})
    tok = [m for m in ob.sent if m["kind"] == "password_reset"][-1]["token"]
    r = c.post("/password-reset/confirm", json={"token": tok, "new_password": "brand-new-password"})
    assert r.status_code == 200 and login(c, "r@x.com", "brand-new-password").status_code == 200


def test_reset_proves_mailbox_ownership_so_preregistered_password_dies():
    """Pre-hijack: attacker signs up with the victim's address; victim later resets."""
    c, ob, _, _ = make()
    c.post("/signup", json={"email": "v@x.com", "password": "attacker-chosen-pw", "org_name": "Evil"})
    c.post("/password-reset/request", params={"email": "v@x.com"})
    tok = [m for m in ob.sent if m["kind"] == "password_reset"][-1]["token"]
    c.post("/password-reset/confirm", json={"token": tok, "new_password": "victim-chosen-pw-1"})
    assert login(c, "v@x.com", "attacker-chosen-pw").status_code == 401
    assert login(c, "v@x.com", "victim-chosen-pw-1").status_code == 200


# ---- concurrency ------------------------------------------------------------------------------
def _hammer(fn, n=16):
    out, errs, barrier = [], [], threading.Barrier(n)

    def run(i):
        barrier.wait()
        try:
            out.append(fn(i))
        except Exception as e:  # noqa: BLE001 - the point is to observe any failure
            errs.append(e)

    ts = [threading.Thread(target=run, args=(i,)) for i in range(n)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    return out, errs


def test_shared_db_survives_concurrent_requests():
    c, ob, _, _ = make()
    h = signup(c, ob, "c@x.com")
    lid = mkloc(c, h)
    code = c.post("/pairing", params={"location_id": lid}, headers=h).json()["code"]
    dev = {"Authorization": "Bearer " + c.post("/edge/pair", params={"code": code}).json()["token"]}

    def ingest(i):
        batch = [{"event_id": f"t{i}-{k}", "t": 1.0 + k, "table_id": "T", "kind": "seated", "detail": {}}
                 for k in range(40)]
        r = c.post("/edge/events", json=batch, headers=dev)
        assert r.status_code == 200
        assert c.get("/events", params={"location_id": lid}, headers=h).status_code == 200
        return r.json()["accepted"]

    out, errs = _hammer(ingest)
    assert not errs and sum(out) == 16 * 40
    assert len(c.get("/events", params={"location_id": lid, "limit": 5000}, headers=h).json()) == 640


def test_pairing_code_and_invite_cannot_be_redeemed_twice_in_a_race():
    c, ob, _, _ = make()
    h = signup(c, ob, "c@x.com")
    lid = mkloc(c, h)
    code = c.post("/pairing", params={"location_id": lid}, headers=h).json()["code"]
    out, errs = _hammer(lambda i: c.post("/edge/pair", params={"code": code}).status_code)
    assert not errs
    assert out.count(200) == 1
    c.post("/invites", params={"email": "n@x.com", "role": "host", "location_id": lid}, headers=h)
    tok = [m for m in ob.sent if m["kind"] == "invite"][-1]["token"]
    out, errs = _hammer(lambda i: c.post("/invites/accept", json={"token": tok, "password": PW}).status_code)
    assert not errs and out.count(200) == 1


def test_failed_transaction_leaves_no_partial_rows():
    c, ob, app, _ = make()
    db = app.state.db
    try:
        with db.tx():
            db.execute("INSERT INTO orgs(id,name,created_at) VALUES('x','x',0)")
            raise RuntimeError("boom")
    except RuntimeError:
        pass
    assert db.execute("SELECT COUNT(*) c FROM orgs").fetchone()["c"] == 0
