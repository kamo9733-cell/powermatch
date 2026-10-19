"""HTTP API. Golden rule: org_id ALWAYS comes from the authenticated session, never from the request.

Hardening notes (see docs/SECURITY_REVIEW.md): one lock-guarded DB connection with atomic `tx()` blocks,
single-use tokens claimed with DELETE-and-check-rowcount, per-IP + per-identity rate limits, uniform work
for known/unknown accounts, bounded inputs, security headers + body limit as ASGI middleware, and an audit
trail for logins, role changes and every read of guest-derived data.
"""
import contextvars
import csv
import io
import json
import logging
import re
import time
import uuid
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field, StringConstraints, field_validator

from . import billing, rbac, security
from .db import connect

log = logging.getLogger("tablesight.platform")

SESSION_TTL = 12 * 3600      # absolute lifetime
IDLE_TTL = 4 * 3600          # sliding inactivity limit
MAX_SESSIONS = 20            # per user; oldest are evicted
MAX_FAILED, LOCK_S = 5, 900
MAX_BODY = 4 * 2**20
FUTURE_SLACK_S = 300         # edge clocks may run ahead this much
MAX_BATCH, MAX_DETAIL_BYTES, MAX_DETAIL_DEPTH = 1000, 2048, 5
MAX_EXPORT_ROWS = 100_000
PAIR_CODE_TTL, MAX_LIVE_CODES = 900, 10
AUDIT_READ_DEDUPE_S = 60
CAMERA_SCHEMES = {"rtsp", "rtsps", "http", "https"}

EMAIL_RE = r"^[^@\s]{1,64}@[^@\s]{1,189}\.[^@\s]{2,63}$"
Email = Annotated[str, StringConstraints(strip_whitespace=True, to_lower=True, max_length=254, pattern=EMAIL_RE)]
Password = Annotated[str, StringConstraints(min_length=1, max_length=256)]
Ident = Annotated[str, StringConstraints(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.:\-]+$")]

CLIENT_IP: contextvars.ContextVar[str] = contextvars.ContextVar("client_ip", default="unknown")

SEC_HEADERS = [
    (b"content-security-policy", b"default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"),
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"no-referrer"),
    (b"cache-control", b"no-store"),
    (b"pragma", b"no-cache"),
    (b"strict-transport-security", b"max-age=31536000; includeSubDomains"),
    (b"permissions-policy", b"camera=(), microphone=(), geolocation=()"),
    (b"cross-origin-resource-policy", b"same-origin"),
]
_SEC_NAMES = {k for k, _ in SEC_HEADERS}

# Org purge: literal statements only, never an interpolated table name.
ORG_PURGE = (
    "DELETE FROM events WHERE org_id=?", "DELETE FROM cameras WHERE org_id=?",
    "DELETE FROM devices WHERE org_id=?", "DELETE FROM pairing WHERE org_id=?",
    "DELETE FROM corrections WHERE org_id=?", "DELETE FROM webhooks WHERE org_id=?",
    "DELETE FROM locations WHERE org_id=?", "DELETE FROM invites WHERE org_id=?",
)


class _TooLarge(Exception):
    pass


class Hardening:
    """ASGI middleware: client IP for the audit trail, request-size cap, security headers on EVERY
    response (including 4xx/5xx), and a last-resort 500 that leaks nothing."""

    def __init__(self, app, max_body: int = MAX_BODY):
        self.app, self.max_body = app, max_body

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        client = scope.get("client")
        tok = CLIENT_IP.set(client[0] if client else "unknown")
        started = False

        async def send2(msg):
            nonlocal started
            if msg["type"] == "http.response.start":
                started = True
                keep = [(k, v) for k, v in msg.get("headers", []) if k.lower() not in _SEC_NAMES]
                msg = {**msg, "headers": keep + SEC_HEADERS}
            await send(msg)

        async def reply(status: int, detail: str):
            await send2({"type": "http.response.start", "status": status,
                         "headers": [(b"content-type", b"application/json")]})
            await send2({"type": "http.response.body", "body": json.dumps({"detail": detail}).encode()})

        try:
            cl = dict(scope["headers"]).get(b"content-length", b"")
            if cl.isdigit() and int(cl) > self.max_body:
                return await reply(413, "request too large")
            seen = 0

            async def recv2():
                nonlocal seen
                m = await receive()
                if m["type"] == "http.request":
                    seen += len(m.get("body", b""))
                    if seen > self.max_body:
                        raise _TooLarge
                return m

            await self.app(scope, recv2, send2)
        except _TooLarge:
            if not started:
                await reply(413, "request too large")
        except Exception:  # last resort: log server side, tell the client nothing
            log.exception("unhandled error")
            if not started:
                await reply(500, "internal error")
        finally:
            CLIENT_IP.reset(tok)


class Outbox:
    """Notification interface (email/SMS/push). Default: in-memory, self-hostable; real senders plug in."""

    def __init__(self):
        self.sent: list[dict] = []

    def send(self, to: str, kind: str, token: str) -> None:
        self.sent.append({"to": to, "kind": kind, "token": token})


class Cred(BaseModel):
    email: Email
    password: Password
    totp: str | None = Field(default=None, max_length=16)


class Signup(BaseModel):
    email: Email
    password: str = Field(min_length=10, max_length=256)
    org_name: str = Field(min_length=1, max_length=120)


class ResetBody(BaseModel):
    token: str = Field(max_length=200)
    new_password: str = Field(max_length=256)


class AcceptBody(BaseModel):
    token: str = Field(max_length=200)
    password: str | None = Field(default=None, max_length=256)


class EventIn(BaseModel):
    event_id: Ident
    t: float = Field(allow_inf_nan=False)
    table_id: str = Field(min_length=1, max_length=64, pattern=r"^[^\x00-\x1f\x7f]+$")
    kind: Ident
    detail: dict = Field(default_factory=dict)

    @field_validator("detail")
    @classmethod
    def _bounded(cls, v: dict) -> dict:
        def depth(x, d=1):
            if d > MAX_DETAIL_DEPTH:
                raise ValueError("detail nested too deeply")
            for y in (x.values() if isinstance(x, dict) else x if isinstance(x, list) else ()):
                depth(y, d + 1)
        depth(v)
        if len(json.dumps(v)) > MAX_DETAIL_BYTES:
            raise ValueError("detail too large")
        return v


def _norm_email(e: str) -> str:
    e = e.strip().lower()
    if len(e) > 254 or not re.match(EMAIL_RE, e):
        raise HTTPException(422, "invalid email")
    return e


def create_app(db_path: str = ":memory:", vault_key: bytes | None = None, outbox: Outbox | None = None,
               billing_provider: billing.BillingProvider | None = None, clock=None,
               allow_self_serve_plan: bool = True, enable_docs: bool = False) -> FastAPI:
    """`allow_self_serve_plan=False` (set by `python -m tablesight.platform` unless overridden) stops an
    owner from upgrading their own plan without payment; only downgrades are then self-service."""
    db = connect(db_path)
    vault = security.Vault(vault_key)
    out = outbox or Outbox()
    bill = billing_provider or billing.NoopProvider()
    now = clock or time.time
    lim = {
        "login_ip": security.RateLimiter(30, 60), "login_email": security.RateLimiter(10, 60),
        "signup_ip": security.RateLimiter(20, 3600), "signup_email": security.RateLimiter(3, 3600),
        "reset_ip": security.RateLimiter(20, 3600), "reset_email": security.RateLimiter(3, 3600),
        "token_ip": security.RateLimiter(60, 60),
        "pair_fail_ip": security.RateLimiter(10, 300), "pair_fail_all": security.RateLimiter(300, 300),
        "invite_user": security.RateLimiter(30, 3600), "ingest_dev": security.RateLimiter(120, 60),
    }
    app = FastAPI(title="TableSight API", version="0.1.0",
                  docs_url="/docs" if enable_docs else None, redoc_url="/redoc" if enable_docs else None,
                  openapi_url="/openapi.json" if enable_docs else None)
    app.add_middleware(Hardening)
    app.state.db, app.state.outbox, app.state.billing, app.state.clock = db, out, bill, now

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError):
        # FastAPI's default echoes the offending INPUT back, which would reflect passwords/tokens.
        errs = [{"loc": list(e["loc"]), "msg": e["msg"], "type": e["type"]} for e in exc.errors()]
        return JSONResponse({"detail": errs}, status_code=422)

    @app.exception_handler(RecursionError)
    async def _deep(_: Request, exc: RecursionError):
        return JSONResponse({"detail": "malformed request"}, status_code=400)

    def ip() -> str:
        return CLIENT_IP.get()

    def audit(org: str, user: str | None, action: str, target: str = "") -> None:
        db.execute("INSERT INTO audit(org_id,user_id,action,target,t,ip) VALUES(?,?,?,?,?,?)",
                   (org, user, action, target[:300], now(), ip()))
        db.commit()

    def audit_once(org: str, user: str, action: str, target: str) -> None:
        """Reads are audited too, de-duplicated so a polling dashboard does not flood the log."""
        with db.tx():
            if db.execute("SELECT 1 FROM audit WHERE org_id=? AND user_id=? AND action=? AND target=? AND t>?",
                          (org, user, action, target, now() - AUDIT_READ_DEDUPE_S)).fetchone():
                return
            audit(org, user, action, target)

    def audit_user(user_id: str, action: str, target: str = "") -> None:
        for r in db.execute("SELECT org_id FROM memberships WHERE user_id=?", (user_id,)).fetchall():
            audit(r["org_id"], user_id, action, target)

    def throttle(name: str, key: str) -> None:
        if not lim[name].allow(key, now()):
            raise HTTPException(429, "too many requests")

    def me(authorization: str = Header(default="")) -> dict:
        tok = security.bearer(authorization)
        s = db.execute("SELECT * FROM sessions WHERE token_hash=?", (security.digest(tok),)).fetchone() if tok else None
        t = now()
        if not s:
            raise HTTPException(401, "not authenticated")
        last = s["last_seen"] or (s["expires"] - SESSION_TTL)
        if s["expires"] < t or t - last > IDLE_TTL:
            db.execute("DELETE FROM sessions WHERE token_hash=?", (s["token_hash"],))
            db.commit()
            raise HTTPException(401, "not authenticated")
        m = db.execute("SELECT * FROM memberships WHERE user_id=? AND org_id=?",
                       (s["user_id"], s["org_id"])).fetchone()
        if not m:
            raise HTTPException(401, "membership revoked")
        if t - last > 60:
            db.execute("UPDATE sessions SET last_seen=? WHERE token_hash=?", (t, s["token_hash"]))
            db.commit()
        return {"user_id": s["user_id"], "org_id": s["org_id"], "role": m["role"], "session_id": s["id"],
                "location_id": m["location_id"], "section": m["section"], "token_hash": s["token_hash"]}

    def need(ctx: dict, perm: str) -> None:
        if not rbac.can(ctx["role"], perm):
            raise HTTPException(403, f"missing permission {perm}")

    def loc_ok(ctx: dict, location_id: str) -> None:
        """Location-scoped roles may touch only their own location; org roles any in THEIR org."""
        row = db.execute("SELECT 1 FROM locations WHERE id=? AND org_id=?", (location_id, ctx["org_id"])).fetchone()
        if not row:
            raise HTTPException(404, "location not found")  # same answer for other tenants' ids
        if ctx["role"] in rbac.LOCATION_SCOPED and ctx["location_id"] != location_id:
            raise HTTPException(404, "location not found")

    def new_session(user_id: str, org_id: str, ua: str) -> str:
        t, tok = now(), security.new_token()
        with db.tx():
            db.execute("DELETE FROM sessions WHERE expires<?", (t,))
            db.execute("DELETE FROM sessions WHERE user_id=? AND token_hash NOT IN "
                       "(SELECT token_hash FROM sessions WHERE user_id=? ORDER BY created DESC LIMIT ?)",
                       (user_id, user_id, MAX_SESSIONS - 1))
            db.execute("INSERT INTO sessions(token_hash,user_id,org_id,expires,id,created,last_seen,ip,ua) "
                       "VALUES(?,?,?,?,?,?,?,?,?)",
                       (security.digest(tok), user_id, org_id, t + SESSION_TTL, uuid.uuid4().hex, t, t, ip(), ua[:200]))
        return tok

    def claim(table: str, token: str, purpose: str | None = None):
        """Atomically consume a single-use token: only ONE concurrent caller can win the DELETE."""
        h = security.digest(token)
        if table == "tokens":
            r = db.execute("SELECT * FROM tokens WHERE token_hash=? AND purpose=?", (h, purpose)).fetchone()
            gone = db.execute("DELETE FROM tokens WHERE token_hash=? AND purpose=?", (h, purpose))
        else:
            r = db.execute("SELECT * FROM invites WHERE token_hash=?", (h,)).fetchone()
            gone = db.execute("DELETE FROM invites WHERE token_hash=?", (h,))
        if not r or gone.rowcount != 1 or r["expires"] < now():
            return None
        return r

    # ---- auth -------------------------------------------------------------------------------
    @app.post("/signup")
    def signup(b: Signup):
        throttle("signup_ip", ip())
        pw = security.hash_password(b.password)  # always hash: same cost whether or not the email exists
        org, uid = uuid.uuid4().hex, uuid.uuid4().hex
        with db.tx():
            if db.execute("SELECT 1 FROM users WHERE email=?", (b.email,)).fetchone():
                # Same response as success: signup must not reveal who is already registered.
                if lim["signup_email"].allow(b.email, now()):
                    out.send(b.email, "account_exists", "")
                return {"org_id": org}
            db.execute("INSERT INTO orgs(id,name,created_at) VALUES(?,?,?)", (org, b.org_name, now()))
            db.execute("INSERT INTO users(id,email,pw) VALUES(?,?,?)", (uid, b.email, pw))
            db.execute("INSERT INTO memberships(user_id,org_id,role) VALUES(?,?,'owner')", (uid, org))
            tok = security.new_token()
            db.execute("INSERT INTO tokens VALUES(?,?,?,?)", (security.digest(tok), "verify", uid, now() + 86400))
            audit(org, uid, "signup")
        out.send(b.email, "verify_email", tok)
        return {"org_id": org}

    @app.post("/verify-email")
    def verify_email(token: Annotated[str, Query(max_length=200)]):
        throttle("token_ip", ip())
        with db.tx():
            r = claim("tokens", token, "verify")
            if not r:
                raise HTTPException(400, "invalid or expired token")
            db.execute("UPDATE users SET verified=1 WHERE id=?", (r["user_id"],))
        return {"ok": True}

    @app.post("/login")
    def login(b: Cred, request: Request):
        throttle("login_ip", ip())
        throttle("login_email", b.email)
        t = now()
        lf = db.execute("SELECT * FROM login_fail WHERE email=?", (b.email,)).fetchone()
        if lf and lf["locked_until"] > t:  # unknown and known emails lock identically
            raise HTTPException(423, "account temporarily locked")
        u = db.execute("SELECT * FROM users WHERE email=?", (b.email,)).fetchone()
        # Exactly one scrypt either way, so response time does not reveal whether the account exists.
        ok = security.verify_password(b.password, u["pw"] if u else security.DUMMY_HASH)

        def fail() -> HTTPException:
            with db.tx():
                row = db.execute("SELECT failed FROM login_fail WHERE email=?", (b.email,)).fetchone()
                failed = (row["failed"] if row else 0) + 1
                lock = t + LOCK_S if failed >= MAX_FAILED else 0
                db.execute("INSERT OR REPLACE INTO login_fail(email,failed,locked_until) VALUES(?,?,?)",
                           (b.email, 0 if lock else failed, lock))
                if lock and u:
                    audit_user(u["id"], "login.lockout")
            return HTTPException(401, "invalid credentials")

        if not u or not ok:
            raise fail()
        if not u["verified"]:
            raise HTTPException(403, "email not verified")
        step = None
        if u["totp_secret"]:
            if not b.totp:
                raise HTTPException(401, "2fa code required")
            step = security.totp_step(u["totp_secret"], b.totp, t)
            if step is None or step <= (u["totp_last"] or 0):  # wrong, or a replay of a used code
                raise fail()
        m = db.execute("SELECT org_id FROM memberships WHERE user_id=? LIMIT 1", (u["id"],)).fetchone()
        if not m:
            raise HTTPException(403, "no organization access")
        with db.tx():
            db.execute("DELETE FROM login_fail WHERE email=?", (b.email,))
            if step is not None:
                db.execute("UPDATE users SET totp_last=? WHERE id=?", (step, u["id"]))
            tok = new_session(u["id"], m["org_id"], request.headers.get("user-agent", ""))
            audit(m["org_id"], u["id"], "login")
        return {"token": tok}

    @app.post("/logout")
    def logout(ctx: dict = Depends(me)):
        db.execute("DELETE FROM sessions WHERE token_hash=?", (ctx["token_hash"],))
        audit(ctx["org_id"], ctx["user_id"], "logout")
        return {"ok": True}

    @app.post("/logout-all")
    def logout_all(ctx: dict = Depends(me)):
        """Revoke EVERY session of this user (lost laptop, suspected token theft), including this one."""
        with db.tx():
            n = db.execute("DELETE FROM sessions WHERE user_id=?", (ctx["user_id"],)).rowcount
            audit(ctx["org_id"], ctx["user_id"], "logout_all", str(n))
        return {"revoked": n}

    @app.get("/sessions")
    def sessions(ctx: dict = Depends(me)):
        rows = db.execute("SELECT id,created,last_seen,ip,ua FROM sessions WHERE user_id=? ORDER BY created DESC",
                          (ctx["user_id"],)).fetchall()
        return [{**dict(r), "current": r["id"] == ctx["session_id"]} for r in rows]

    @app.delete("/sessions/{sid}")
    def revoke_session(sid: str, ctx: dict = Depends(me)):
        n = db.execute("DELETE FROM sessions WHERE id=? AND user_id=?", (sid, ctx["user_id"])).rowcount
        if not n:
            raise HTTPException(404, "session not found")  # also the answer for other users' ids
        audit(ctx["org_id"], ctx["user_id"], "session.revoke", sid)
        return {"ok": True}

    @app.post("/2fa/setup")
    def twofa_setup(current_totp: Annotated[str | None, Query(max_length=16)] = None, ctx: dict = Depends(me)):
        u = db.execute("SELECT totp_secret, totp_last FROM users WHERE id=?", (ctx["user_id"],)).fetchone()
        last = 0
        if u["totp_secret"]:  # replacing live 2FA needs a fresh code: a stolen session alone is not enough
            step = security.totp_step(u["totp_secret"], current_totp or "", now())
            if step is None or step <= (u["totp_last"] or 0):
                raise HTTPException(409, "2fa already enabled: supply current_totp to replace it")
            last = step
        sec = security.new_totp_secret()
        with db.tx():
            db.execute("UPDATE users SET totp_secret=?, totp_last=? WHERE id=?", (sec, last, ctx["user_id"]))
            audit(ctx["org_id"], ctx["user_id"], "2fa.setup")
        return {"secret": sec}

    @app.post("/password-reset/request")
    def reset_request(email: str):
        email = _norm_email(email)
        throttle("reset_ip", ip())
        if not lim["reset_email"].allow(email, now()):
            return {"ok": True}  # silent: a 429 here would be keyed on the address, not on its existence
        u = db.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()
        if u:
            tok = security.new_token()
            with db.tx():
                db.execute("DELETE FROM tokens WHERE user_id=? AND purpose='reset'", (u["id"],))  # supersede
                db.execute("INSERT INTO tokens VALUES(?,?,?,?)", (security.digest(tok), "reset", u["id"], now() + 3600))
                audit_user(u["id"], "password.reset_request")
            out.send(email, "password_reset", tok)
        return {"ok": True}  # identical response whether or not the account exists

    @app.post("/password-reset/confirm")
    def reset_confirm(body: ResetBody | None = None, token: Annotated[str | None, Query(max_length=200)] = None,
                      new_password: Annotated[str | None, Query(max_length=256)] = None):
        """Secrets belong in the JSON body (URLs end up in proxy/access logs); query form kept for compat."""
        throttle("token_ip", ip())
        token, new_password = (body.token, body.new_password) if body else (token, new_password)
        if not token or not new_password or len(new_password) < 10:
            raise HTTPException(400, "invalid request")
        pw = security.hash_password(new_password)
        with db.tx():
            r = claim("tokens", token, "reset")
            if not r:
                raise HTTPException(400, "invalid request")
            u = db.execute("SELECT email FROM users WHERE id=?", (r["user_id"],)).fetchone()
            # Holding the mailbox proves ownership: also verifies, which neutralises a password an
            # attacker pre-registered for this address.
            db.execute("UPDATE users SET pw=?, verified=1 WHERE id=?", (pw, r["user_id"]))
            db.execute("DELETE FROM login_fail WHERE email=?", (u["email"],))
            db.execute("DELETE FROM tokens WHERE user_id=? AND purpose='reset'", (r["user_id"],))
            db.execute("DELETE FROM sessions WHERE user_id=?", (r["user_id"],))  # kill old sessions
            audit_user(r["user_id"], "password.reset")
        return {"ok": True}

    # ---- invites & members --------------------------------------------------------------------
    @app.post("/invites")
    def invite(email: str, role: str, location_id: str | None = None,
               section: Annotated[str | None, Query(max_length=64)] = None, ctx: dict = Depends(me)):
        need(ctx, "invite")
        throttle("invite_user", ctx["user_id"])
        email = _norm_email(email)
        if not rbac.can_assign(ctx["role"], role):
            raise HTTPException(403, "cannot grant that role")
        if role in rbac.LOCATION_SCOPED:
            if not location_id:
                raise HTTPException(422, "location_id required for this role")
            loc_ok(ctx, location_id)
        else:
            location_id = None  # org-wide roles never carry a (possibly foreign) location
        tok = security.new_token()
        with db.tx():
            db.execute("DELETE FROM invites WHERE org_id=? AND email=?", (ctx["org_id"], email))
            db.execute("INSERT INTO invites(token_hash,org_id,email,role,location_id,expires,inviter,section) "
                       "VALUES(?,?,?,?,?,?,?,?)",
                       (security.digest(tok), ctx["org_id"], email, role, location_id, now() + 7 * 86400,
                        ctx["user_id"], section))
            audit(ctx["org_id"], ctx["user_id"], "invite", f"{email}:{role}")
        out.send(email, "invite", tok)
        return {"ok": True}

    @app.post("/invites/accept")
    def accept(body: AcceptBody | None = None, token: Annotated[str | None, Query(max_length=200)] = None,
               password: Annotated[str | None, Query(max_length=256)] = None):
        throttle("token_ip", ip())
        token, password = (body.token, body.password) if body else (token, password)
        if not token:
            raise HTTPException(400, "invalid or expired invite")
        pw = security.hash_password(password) if password and len(password) >= 10 else None
        bad = HTTPException(400, "invalid or expired invite")
        with db.tx():
            r = claim("invites", token)
            if not r:
                raise bad
            # The invite is only as good as its sender's authority AT ACCEPT TIME.
            inv = db.execute("SELECT role, location_id FROM memberships WHERE user_id=? AND org_id=?",
                             (r["inviter"], r["org_id"])).fetchone() if r["inviter"] else None
            if not inv or not rbac.can(inv["role"], "invite") or not rbac.can_assign(inv["role"], r["role"]):
                raise bad
            if inv["role"] in rbac.LOCATION_SCOPED and inv["location_id"] != r["location_id"]:
                raise bad
            if r["role"] in rbac.LOCATION_SCOPED and not db.execute(
                    "SELECT 1 FROM locations WHERE id=? AND org_id=?", (r["location_id"], r["org_id"])).fetchone():
                raise bad
            u = db.execute("SELECT id, verified FROM users WHERE email=?", (r["email"],)).fetchone()
            if not u:
                if not pw:
                    raise HTTPException(422, "password required (min 10 chars)")
                uid = uuid.uuid4().hex
                db.execute("INSERT INTO users(id,email,pw,verified) VALUES(?,?,?,1)", (uid, r["email"], pw))
            else:
                uid = u["id"]
                if not u["verified"] and pw:  # unverified pre-registered account: the invitee takes it over
                    db.execute("UPDATE users SET pw=?, verified=1 WHERE id=?", (pw, uid))
                    db.execute("DELETE FROM sessions WHERE user_id=?", (uid,))
                cur = db.execute("SELECT role FROM memberships WHERE user_id=? AND org_id=?", (uid, r["org_id"])).fetchone()
                if cur and rbac.rank(cur["role"]) >= rbac.rank(r["role"]):
                    raise HTTPException(409, "already a member with equal or higher role")
            db.execute("INSERT OR REPLACE INTO memberships(user_id,org_id,role,location_id,section) VALUES(?,?,?,?,?)",
                       (uid, r["org_id"], r["role"], r["location_id"], r["section"]))
            audit(r["org_id"], uid, "invite.accept", f"{r['role']} by {r['inviter']}")
        return {"ok": True}

    def target_member(ctx: dict, uid: str):
        """Membership the actor may manage: same org, in scope, strictly below the actor's own rank."""
        need(ctx, "invite")
        m = db.execute("SELECT * FROM memberships WHERE user_id=? AND org_id=?", (uid, ctx["org_id"])).fetchone()
        if not m or (ctx["role"] in rbac.LOCATION_SCOPED and m["location_id"] != ctx["location_id"]):
            raise HTTPException(404, "member not found")
        if not rbac.can_assign(ctx["role"], m["role"]):
            raise HTTPException(403, "cannot manage a member of equal or higher role")
        return m

    @app.get("/members")
    def members(ctx: dict = Depends(me)):
        need(ctx, "invite")
        q = ("SELECT m.user_id, u.email, m.role, m.location_id, m.section FROM memberships m "
             "JOIN users u ON u.id=m.user_id WHERE m.org_id=?")
        a: list = [ctx["org_id"]]
        if ctx["role"] in rbac.LOCATION_SCOPED:
            q, a = q + " AND m.location_id=?", a + [ctx["location_id"]]
        return [dict(r) for r in db.execute(q, a)]

    @app.patch("/members/{uid}")
    def change_member(uid: str, role: str, section: Annotated[str | None, Query(max_length=64)] = None,
                      ctx: dict = Depends(me)):
        m = target_member(ctx, uid)
        if not rbac.can_assign(ctx["role"], role):
            raise HTTPException(403, "cannot grant that role")
        loc = m["location_id"] if role in rbac.LOCATION_SCOPED else None
        if role in rbac.LOCATION_SCOPED:
            if not loc:
                raise HTTPException(422, "member has no location; re-invite instead")
            loc_ok(ctx, loc)
        with db.tx():
            db.execute("UPDATE memberships SET role=?, location_id=?, section=? WHERE user_id=? AND org_id=?",
                       (role, loc, section, uid, ctx["org_id"]))
            audit(ctx["org_id"], ctx["user_id"], "member.role_change", f"{uid}:{m['role']}->{role}")
        return {"ok": True}

    @app.delete("/members/{uid}")
    def remove_member(uid: str, ctx: dict = Depends(me)):
        m = target_member(ctx, uid)
        with db.tx():
            db.execute("DELETE FROM memberships WHERE user_id=? AND org_id=?", (uid, ctx["org_id"]))
            db.execute("DELETE FROM sessions WHERE user_id=? AND org_id=?", (uid, ctx["org_id"]))
            audit(ctx["org_id"], ctx["user_id"], "member.remove", f"{uid}:{m['role']}")
        return {"ok": True}

    # ---- locations & cameras ----------------------------------------------------------------
    def plan_of(org_id: str) -> billing.Plan:
        return billing.PLANS[db.execute("SELECT plan FROM orgs WHERE id=?", (org_id,)).fetchone()["plan"]]

    @app.post("/locations")
    def add_location(name: Annotated[str, Query(min_length=1, max_length=120)],
                     venue_type: Annotated[str, Query(pattern=r"^[a-z0-9_]{1,40}$")] = "casual_dining",
                     tz: Annotated[str, Query(max_length=64)] = "UTC", ctx: dict = Depends(me)):
        need(ctx, "location.write")
        try:
            ZoneInfo(tz)
        except Exception:  # noqa: BLE001 - any failure to resolve means invalid
            raise HTTPException(422, "unknown time zone") from None
        with db.tx():
            n = db.execute("SELECT COUNT(*) c FROM locations WHERE org_id=?", (ctx["org_id"],)).fetchone()["c"]
            if n >= plan_of(ctx["org_id"]).max_locations:
                raise HTTPException(402, "plan location limit reached")
            lid = uuid.uuid4().hex
            db.execute("INSERT INTO locations(id,org_id,name,venue_type,tz) VALUES(?,?,?,?,?)",
                       (lid, ctx["org_id"], name, venue_type, tz))
            audit(ctx["org_id"], ctx["user_id"], "location.create", lid)
        return {"id": lid}

    @app.get("/locations")
    def list_locations(ctx: dict = Depends(me)):
        q, a = "SELECT id,name,venue_type,tz,staff_analytics,retention_days FROM locations WHERE org_id=?", [ctx["org_id"]]
        if ctx["role"] in rbac.LOCATION_SCOPED:
            q, a = q + " AND id=?", a + [ctx["location_id"]]
        return [dict(r) for r in db.execute(q, a)]

    @app.patch("/locations/{lid}/settings")
    def settings(lid: str, staff_analytics: str | None = None,
                 retention_days: Annotated[int | None, Query(ge=0, le=3650)] = None, ctx: dict = Depends(me)):
        need(ctx, "location.write")
        loc_ok(ctx, lid)
        with db.tx():
            if staff_analytics is not None:
                if staff_analytics not in ("on", "anonymized", "off"):
                    raise HTTPException(422, "staff_analytics must be on|anonymized|off")
                db.execute("UPDATE locations SET staff_analytics=? WHERE id=? AND org_id=?", (staff_analytics, lid, ctx["org_id"]))
            if retention_days is not None:
                plan = plan_of(ctx["org_id"])
                if not 1 <= retention_days <= plan.max_retention_days:
                    raise HTTPException(402, f"retention limited to {plan.max_retention_days} days on this plan")
                db.execute("UPDATE locations SET retention_days=? WHERE id=? AND org_id=?", (retention_days, lid, ctx["org_id"]))
            audit(ctx["org_id"], ctx["user_id"], "location.settings", f"{lid} analytics={staff_analytics} retention={retention_days}")
        return {"ok": True}

    @app.post("/cameras")
    def add_camera(location_id: str, name: Annotated[str, Query(min_length=1, max_length=120)],
                   url: Annotated[str, Query(min_length=1, max_length=2048)], ctx: dict = Depends(me)):
        need(ctx, "camera.write")
        loc_ok(ctx, location_id)
        from urllib.parse import urlparse
        try:
            p = urlparse(url)
            valid = p.scheme in CAMERA_SCHEMES and bool(p.hostname)
        except ValueError:
            valid = False
        if not valid:  # no file://, gopher://, javascript: ... the edge agent will dial this URL
            raise HTTPException(422, "camera url must be rtsp(s):// or http(s):// with a host")
        with db.tx():
            n = db.execute("SELECT COUNT(*) c FROM cameras WHERE org_id=?", (ctx["org_id"],)).fetchone()["c"]
            if n >= plan_of(ctx["org_id"]).max_cameras:
                raise HTTPException(402, "plan camera limit reached")
            cid = uuid.uuid4().hex
            db.execute("INSERT INTO cameras(id,org_id,location_id,name,url_enc) VALUES(?,?,?,?,?)", (cid, ctx["org_id"], location_id, name, vault.seal(url)))
            audit(ctx["org_id"], ctx["user_id"], "camera.create", cid)
        return {"id": cid}

    @app.get("/cameras")
    def list_cameras(location_id: str, ctx: dict = Depends(me)):
        need(ctx, "camera.write")
        loc_ok(ctx, location_id)
        return [dict(r) for r in db.execute("SELECT id,name,angle_score FROM cameras WHERE org_id=? AND location_id=?", (ctx["org_id"], location_id))]

    # ---- edge agent -------------------------------------------------------------------------
    @app.post("/pairing")
    def pairing(location_id: str, ctx: dict = Depends(me)):
        need(ctx, "camera.write")
        loc_ok(ctx, location_id)
        with db.tx():
            db.execute("DELETE FROM pairing WHERE expires<?", (now(),))
            live = db.execute("SELECT COUNT(*) c FROM pairing WHERE org_id=?", (ctx["org_id"],)).fetchone()["c"]
            if live >= MAX_LIVE_CODES:
                raise HTTPException(429, "too many unused pairing codes; wait for them to expire")
            code = security.new_pairing_code()
            db.execute("INSERT INTO pairing VALUES(?,?,?,?)",
                       (security.digest(security.normalize_code(code)), ctx["org_id"], location_id, now() + PAIR_CODE_TTL))
            audit(ctx["org_id"], ctx["user_id"], "pairing.create", location_id)
        return {"code": code, "expires_in_s": PAIR_CODE_TTL}

    @app.post("/edge/pair")
    def edge_pair(code: Annotated[str, Query(max_length=32)]):
        if lim["pair_fail_ip"].blocked(ip(), now()) or lim["pair_fail_all"].blocked("*", now()):
            raise HTTPException(429, "too many failed attempts")
        tok, did = security.new_token(), uuid.uuid4().hex
        with db.tx():
            h = security.digest(security.normalize_code(code))
            r = db.execute("SELECT * FROM pairing WHERE code_hash=?", (h,)).fetchone()
            won = db.execute("DELETE FROM pairing WHERE code_hash=?", (h,)).rowcount == 1  # single use, race-safe
            if r and won and r["expires"] >= now():
                db.execute("INSERT INTO devices(id,org_id,location_id,token_hash,created) VALUES(?,?,?,?,?)",
                           (did, r["org_id"], r["location_id"], security.digest(tok), now()))
                audit(r["org_id"], None, "device.pair", did)
                return {"device_id": did, "token": tok}
        lim["pair_fail_ip"].record(ip(), now())
        lim["pair_fail_all"].record("*", now())
        raise HTTPException(400, "invalid or expired code")

    def device(authorization: str = Header(default="")) -> dict:
        tok = security.bearer(authorization)
        d = db.execute("SELECT * FROM devices WHERE token_hash=?", (security.digest(tok),)).fetchone() if tok else None
        if not d:
            raise HTTPException(401, "unknown device")
        return dict(d)

    @app.post("/edge/events")
    def ingest(events: list[EventIn], d: dict = Depends(device)):
        """Idempotent: replaying the same batch after an outage never duplicates events."""
        if len(events) > MAX_BATCH:
            raise HTTPException(413, "batch too large")
        throttle("ingest_dev", d["id"])
        horizon = now() + FUTURE_SLACK_S
        new = dup = rej = 0
        rejected_ids: list[str] = []
        with db.tx():
            for e in events:
                if e.t < 0 or e.t > horizon:  # clock-skewed or hostile timestamps never reach the store
                    rej += 1
                    rejected_ids.append(e.event_id)  # tell the edge WHICH ones, so it can park, not delete, them
                    continue
                cur = db.execute("INSERT OR IGNORE INTO events(org_id,location_id,event_id,t,table_id,kind,detail) VALUES(?,?,?,?,?,?,?)",
                                 (d["org_id"], d["location_id"], e.event_id, e.t, e.table_id, e.kind, json.dumps(e.detail)))
                new += cur.rowcount
                dup += 1 - cur.rowcount
            db.execute("UPDATE devices SET last_seen=? WHERE id=?", (now(), d["id"]))
        res = {"accepted": new, "duplicates": dup}
        if rej:
            res["rejected"] = rej
            res["rejected_ids"] = rejected_ids[:MAX_BATCH]
        return res

    @app.post("/edge/heartbeat")
    def heartbeat(health: dict, version: Annotated[str, Query(max_length=64)] = "",
                  device_t: Annotated[float | None, Query(allow_inf_nan=False)] = None, d: dict = Depends(device)):
        if len(json.dumps(health)) > 16_384:
            raise HTTPException(413, "health payload too large")
        if device_t is not None:  # RED_TEAM 11: surface edge clock drift instead of silently shifting alerts
            health = {**health, "clock_skew_s": round(now() - device_t, 1)}
        db.execute("UPDATE devices SET last_seen=?, version=?, health=? WHERE id=?", (now(), version, json.dumps(health), d["id"]))
        db.commit()
        return {"ok": True}

    @app.get("/devices")
    def devices(ctx: dict = Depends(me)):
        """Fleet/support view: health only, no video, no credentials. Location roles see their own site."""
        need(ctx, "camera.write")
        q, a = "SELECT id,location_id,last_seen,version,health FROM devices WHERE org_id=?", [ctx["org_id"]]
        if ctx["role"] in rbac.LOCATION_SCOPED:
            q, a = q + " AND location_id=?", a + [ctx["location_id"]]
        return [dict(r) for r in db.execute(q, a)]

    @app.delete("/devices/{device_id}")
    def revoke_device(device_id: str, ctx: dict = Depends(me)):
        need(ctx, "camera.write")
        q, a = "DELETE FROM devices WHERE id=? AND org_id=?", [device_id, ctx["org_id"]]
        if ctx["role"] in rbac.LOCATION_SCOPED:
            q, a = q + " AND location_id=?", a + [ctx["location_id"]]
        if db.execute(q, a).rowcount != 1:
            raise HTTPException(404, "device not found")
        audit(ctx["org_id"], ctx["user_id"], "device.revoke", device_id)
        return {"ok": True}

    # ---- events, export, analytics ----------------------------------------------------------
    def fetch_events(ctx: dict, location_id: str, since: float = 0, limit: int = 5000,
                     event_id: str | None = None) -> list[dict]:
        """Newest `limit` events (returned oldest-first). Section scoping applies to every caller."""
        loc_ok(ctx, location_id)
        q = "SELECT event_id,t,table_id,kind,detail FROM events WHERE org_id=? AND location_id=? AND t>=?"
        a: list = [ctx["org_id"], location_id, since]
        if event_id is not None:
            q, a = q + " AND event_id=?", a + [event_id]
        if rbac.can(ctx["role"], "events.read"):
            pass
        elif rbac.can(ctx["role"], "events.read.own_section"):
            if not ctx["section"]:
                return []
            q, a = q + " AND json_extract(detail,'$.section')=?", a + [ctx["section"]]
        else:
            raise HTTPException(403, "missing permission events.read")
        rows = db.execute(q + " ORDER BY t DESC LIMIT ?", a + [limit]).fetchall()
        return [dict(r, detail=json.loads(r["detail"])) for r in reversed(rows)]

    @app.get("/events")
    def events_list(location_id: str, since: float = 0, limit: Annotated[int, Query(ge=1, le=5000)] = 1000,
                    ctx: dict = Depends(me)):
        res = fetch_events(ctx, location_id, since, limit)
        audit_once(ctx["org_id"], ctx["user_id"], "events.read", location_id)
        return res

    @app.get("/export/events.csv")
    def export(location_id: str, ctx: dict = Depends(me)):
        need(ctx, "export")
        rows = fetch_events(ctx, location_id, 0, MAX_EXPORT_ROWS)
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["event_id", "t", "table_id", "kind", "detail"])
        for r in rows:
            w.writerow([security.csv_safe(r["event_id"]), r["t"], security.csv_safe(r["table_id"]),
                        security.csv_safe(r["kind"]), security.csv_safe(json.dumps(r["detail"]))])
        audit(ctx["org_id"], ctx["user_id"], "export", location_id)
        return Response(buf.getvalue(), media_type="text/csv",
                        headers={"Content-Disposition": 'attachment; filename="events.csv"'})

    @app.get("/analytics/staff-greet-times")
    def staff_greets(location_id: str, ctx: dict = Depends(me)):
        need(ctx, "analytics.staff")
        loc_ok(ctx, location_id)
        mode = db.execute("SELECT staff_analytics FROM locations WHERE id=? AND org_id=?", (location_id, ctx["org_id"])).fetchone()["staff_analytics"]
        if mode == "off":
            raise HTTPException(403, "staff analytics disabled for this location")
        from ..analytics import greet_times
        from ..table import Event
        evs = [Event(r["t"], r["table_id"], r["kind"], r["detail"]) for r in fetch_events(ctx, location_id, 0, MAX_EXPORT_ROWS)]
        audit_once(ctx["org_id"], ctx["user_id"], "staff_analytics.read", location_id)
        g = greet_times(evs)
        return {"mode": mode, "n": len(g), "median_s": sorted(g)[len(g) // 2] if g else None,
                "note": "Team-level only; individual staff are never named in anonymized mode."}

    @app.get("/me")
    def whoami(ctx: dict = Depends(me)):
        u = db.execute("SELECT email, lang FROM users WHERE id=?", (ctx["user_id"],)).fetchone()
        return {"user_id": ctx["user_id"], "email": u["email"], "lang": u["lang"], "org_id": ctx["org_id"],
                "role": ctx["role"], "location_id": ctx["location_id"], "section": ctx["section"],
                "permissions": sorted(rbac.PERMS.get(ctx["role"], set()))}

    @app.post("/alerts/ack")
    def ack_alert(location_id: str, event_id: Annotated[str, Query(min_length=1, max_length=128)],
                  ctx: dict = Depends(me)):
        """Acknowledge a needs_attention event. Idempotent. Servers can only ack events in their own section
        because the lookup goes through the same scoped query as GET /events."""
        need(ctx, "alerts.ack")
        loc_ok(ctx, location_id)
        evs = [e for e in fetch_events(ctx, location_id, 0, 1, event_id=event_id) if e["kind"] == "needs_attention"]
        if not evs:
            raise HTTPException(404, "alert not found")
        with db.tx():
            dup = db.execute("SELECT 1 FROM corrections WHERE org_id=? AND location_id=? AND kind='ack' "
                             "AND json_extract(payload,'$.event_id')=?", (ctx["org_id"], location_id, event_id)).fetchone()
            if not dup:
                db.execute("INSERT INTO corrections(org_id,location_id,kind,payload,consent_training,t) VALUES(?,?,?,?,0,?)",
                           (ctx["org_id"], location_id, "ack",
                            json.dumps({"event_id": event_id, "by": ctx["user_id"], "table": evs[0]["table_id"],
                                        "t": now()}), now()))
        audit(ctx["org_id"], ctx["user_id"], "alert.ack", event_id)
        return {"ok": True, "already": bool(dup)}

    # ---- corrections & data rights ----------------------------------------------------------
    @app.post("/corrections")
    def correction(location_id: str, kind: Annotated[str, Query(min_length=1, max_length=64)], payload: dict,
                   ctx: dict = Depends(me)):
        need(ctx, "corrections.write")
        loc_ok(ctx, location_id)
        blob = json.dumps(payload)
        if len(blob) > 8192:
            raise HTTPException(422, "payload too large")
        db.execute("INSERT INTO corrections(org_id,location_id,kind,payload,consent_training,t) VALUES(?,?,?,?,0,?)", (ctx["org_id"], location_id, kind, blob, now()))
        audit(ctx["org_id"], ctx["user_id"], "correction.create", f"{location_id}:{kind}")
        return {"ok": True}  # never used for model training unless the org opts in later

    @app.get("/audit")
    def audit_log(limit: Annotated[int, Query(ge=1, le=500)] = 500, ctx: dict = Depends(me)):
        need(ctx, "audit.read")
        return [dict(r) for r in db.execute("SELECT user_id,action,target,t,ip FROM audit WHERE org_id=? ORDER BY id DESC LIMIT ?", (ctx["org_id"], limit))]

    @app.delete("/org/data")
    def delete_data(confirm: str, ctx: dict = Depends(me)):
        need(ctx, "data.delete")
        if confirm != "DELETE":
            raise HTTPException(422, "pass confirm=DELETE")
        with db.tx():
            for stmt in ORG_PURGE:
                db.execute(stmt, (ctx["org_id"],))
            audit(ctx["org_id"], ctx["user_id"], "org.data_deleted")
        return {"ok": True}

    @app.post("/billing/plan")
    def set_plan(plan: str, ctx: dict = Depends(me)):
        need(ctx, "billing")
        if plan not in billing.PLANS:
            raise HTTPException(422, "unknown plan")
        order = list(billing.PLANS)
        cur = db.execute("SELECT plan FROM orgs WHERE id=?", (ctx["org_id"],)).fetchone()["plan"]
        if not allow_self_serve_plan and order.index(plan) > order.index(cur):
            raise HTTPException(402, "upgrades go through the billing provider")
        with db.tx():
            db.execute("UPDATE orgs SET plan=? WHERE id=?", (plan, ctx["org_id"]))
            audit(ctx["org_id"], ctx["user_id"], "billing.plan", f"{cur}->{plan}")
        bill.set_plan(ctx["org_id"], plan)
        return {"plan": plan}

    from . import retention
    app.state.purge = lambda: retention.purge(db, now())
    return app
