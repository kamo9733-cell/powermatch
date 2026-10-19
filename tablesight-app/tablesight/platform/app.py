"""HTTP API. Golden rule: org_id ALWAYS comes from the authenticated session, never from the request."""
import csv
import io
import json
import time
import uuid

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from . import billing, rbac, security
from .db import connect

SESSION_TTL = 12 * 3600
MAX_FAILED, LOCK_S = 5, 900


class Outbox:
    """Notification interface (email/SMS/push). Default: in-memory, self-hostable; real senders plug in."""

    def __init__(self):
        self.sent: list[dict] = []

    def send(self, to: str, kind: str, token: str) -> None:
        self.sent.append({"to": to, "kind": kind, "token": token})


class Cred(BaseModel):
    email: str
    password: str
    totp: str | None = None


class Signup(BaseModel):
    email: str
    password: str
    org_name: str


def create_app(db_path: str = ":memory:", vault_key: bytes | None = None, outbox: Outbox | None = None,
               billing_provider: billing.BillingProvider | None = None) -> FastAPI:
    db = connect(db_path)
    vault = security.Vault(vault_key)
    out = outbox or Outbox()
    bill = billing_provider or billing.NoopProvider()
    login_rl = security.RateLimiter(10, 60)
    app = FastAPI(title="TableSight API", version="0.1.0")
    app.state.db, app.state.outbox, app.state.billing = db, out, bill
    now = time.time

    def audit(org: str, user: str | None, action: str, target: str = "") -> None:
        db.execute("INSERT INTO audit(org_id,user_id,action,target,t) VALUES(?,?,?,?,?)",
                   (org, user, action, target, now()))
        db.commit()

    def me(authorization: str = Header(default="")) -> dict:
        tok = authorization.removeprefix("Bearer ").strip()
        s = db.execute("SELECT * FROM sessions WHERE token_hash=?", (security.digest(tok),)).fetchone()
        if not tok or not s or s["expires"] < now():
            raise HTTPException(401, "not authenticated")
        m = db.execute("SELECT * FROM memberships WHERE user_id=? AND org_id=?",
                       (s["user_id"], s["org_id"])).fetchone()
        if not m:
            raise HTTPException(401, "membership revoked")
        return {"user_id": s["user_id"], "org_id": s["org_id"], "role": m["role"],
                "location_id": m["location_id"], "section": m["section"]}

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

    def new_session(user_id: str, org_id: str) -> str:
        t = security.new_token()
        db.execute("INSERT INTO sessions VALUES(?,?,?,?)", (security.digest(t), user_id, org_id, now() + SESSION_TTL))
        db.commit()
        return t

    # ---- auth -------------------------------------------------------------------------------
    @app.post("/signup")
    def signup(b: Signup):
        if len(b.password) < 10:
            raise HTTPException(422, "password must be at least 10 characters")
        if db.execute("SELECT 1 FROM users WHERE email=?", (b.email.lower(),)).fetchone():
            raise HTTPException(409, "email already registered")
        org, uid = uuid.uuid4().hex, uuid.uuid4().hex
        db.execute("INSERT INTO orgs(id,name,created_at) VALUES(?,?,?)", (org, b.org_name, now()))
        db.execute("INSERT INTO users(id,email,pw) VALUES(?,?,?)", (uid, b.email.lower(), security.hash_password(b.password)))
        db.execute("INSERT INTO memberships(user_id,org_id,role) VALUES(?,?,'owner')", (uid, org))
        tok = security.new_token()
        db.execute("INSERT INTO tokens VALUES(?,?,?,?)", (security.digest(tok), "verify", uid, now() + 86400))
        db.commit()
        out.send(b.email, "verify_email", tok)
        audit(org, uid, "signup")
        return {"org_id": org}

    @app.post("/verify-email")
    def verify_email(token: str):
        r = db.execute("SELECT * FROM tokens WHERE token_hash=? AND purpose='verify'", (security.digest(token),)).fetchone()
        if not r or r["expires"] < now():
            raise HTTPException(400, "invalid or expired token")
        db.execute("UPDATE users SET verified=1 WHERE id=?", (r["user_id"],))
        db.execute("DELETE FROM tokens WHERE token_hash=?", (r["token_hash"],))
        db.commit()
        return {"ok": True}

    @app.post("/login")
    def login(b: Cred):
        if not login_rl.allow(b.email.lower()):
            raise HTTPException(429, "too many attempts")
        u = db.execute("SELECT * FROM users WHERE email=?", (b.email.lower(),)).fetchone()
        generic = HTTPException(401, "invalid credentials")  # no user enumeration
        if not u:
            security.verify_password(b.password, security.hash_password("x"))  # constant-ish time
            raise generic
        if u["locked_until"] > now():
            raise HTTPException(423, "account temporarily locked")
        if not security.verify_password(b.password, u["pw"]):
            failed = u["failed"] + 1
            lock = now() + LOCK_S if failed >= MAX_FAILED else 0
            db.execute("UPDATE users SET failed=?, locked_until=? WHERE id=?", (0 if lock else failed, lock, u["id"]))
            db.commit()
            raise generic
        if not u["verified"]:
            raise HTTPException(403, "email not verified")
        if u["totp_secret"] and not (b.totp and security.verify_totp(u["totp_secret"], b.totp)):
            raise HTTPException(401, "2fa code required")
        db.execute("UPDATE users SET failed=0 WHERE id=?", (u["id"],))
        m = db.execute("SELECT org_id FROM memberships WHERE user_id=? LIMIT 1", (u["id"],)).fetchone()
        return {"token": new_session(u["id"], m["org_id"])}

    @app.post("/logout")
    def logout(authorization: str = Header(default=""), ctx: dict = Depends(me)):
        db.execute("DELETE FROM sessions WHERE token_hash=?", (security.digest(authorization.removeprefix("Bearer ").strip()),))
        db.commit()
        return {"ok": True}

    @app.post("/2fa/setup")
    def twofa_setup(ctx: dict = Depends(me)):
        sec = security.new_totp_secret()
        db.execute("UPDATE users SET totp_secret=? WHERE id=?", (sec, ctx["user_id"]))
        db.commit()
        return {"secret": sec}

    @app.post("/password-reset/request")
    def reset_request(email: str):
        u = db.execute("SELECT id FROM users WHERE email=?", (email.lower(),)).fetchone()
        if u:
            tok = security.new_token()
            db.execute("INSERT INTO tokens VALUES(?,?,?,?)", (security.digest(tok), "reset", u["id"], now() + 3600))
            db.commit()
            out.send(email, "password_reset", tok)
        return {"ok": True}  # identical response whether or not the account exists

    @app.post("/password-reset/confirm")
    def reset_confirm(token: str, new_password: str):
        r = db.execute("SELECT * FROM tokens WHERE token_hash=? AND purpose='reset'", (security.digest(token),)).fetchone()
        if not r or r["expires"] < now() or len(new_password) < 10:
            raise HTTPException(400, "invalid request")
        db.execute("UPDATE users SET pw=?, failed=0, locked_until=0 WHERE id=?", (security.hash_password(new_password), r["user_id"]))
        db.execute("DELETE FROM tokens WHERE token_hash=?", (r["token_hash"],))
        db.execute("DELETE FROM sessions WHERE user_id=?", (r["user_id"],))  # kill old sessions
        db.commit()
        return {"ok": True}

    # ---- invites ----------------------------------------------------------------------------
    @app.post("/invites")
    def invite(email: str, role: str, location_id: str | None = None, ctx: dict = Depends(me)):
        need(ctx, "invite")
        if not rbac.can_assign(ctx["role"], role):
            raise HTTPException(403, "cannot grant that role")
        if role in rbac.LOCATION_SCOPED:
            if not location_id:
                raise HTTPException(422, "location_id required for this role")
            loc_ok(ctx, location_id)
        tok = security.new_token()
        db.execute("INSERT INTO invites VALUES(?,?,?,?,?,?)", (security.digest(tok), ctx["org_id"], email.lower(), role, location_id, now() + 7 * 86400))
        db.commit()
        out.send(email, "invite", tok)
        audit(ctx["org_id"], ctx["user_id"], "invite", f"{email}:{role}")
        return {"ok": True}

    @app.post("/invites/accept")
    def accept(token: str, password: str | None = None):
        r = db.execute("SELECT * FROM invites WHERE token_hash=?", (security.digest(token),)).fetchone()
        if not r or r["expires"] < now():
            raise HTTPException(400, "invalid or expired invite")
        u = db.execute("SELECT id FROM users WHERE email=?", (r["email"],)).fetchone()
        if not u:
            if not password or len(password) < 10:
                raise HTTPException(422, "password required (min 10 chars)")
            uid = uuid.uuid4().hex
            db.execute("INSERT INTO users(id,email,pw,verified) VALUES(?,?,?,1)", (uid, r["email"], security.hash_password(password)))
        else:
            uid = u["id"]
        db.execute("INSERT OR REPLACE INTO memberships(user_id,org_id,role,location_id) VALUES(?,?,?,?)", (uid, r["org_id"], r["role"], r["location_id"]))
        db.execute("DELETE FROM invites WHERE token_hash=?", (r["token_hash"],))
        db.commit()
        return {"ok": True}

    # ---- locations & cameras ----------------------------------------------------------------
    @app.post("/locations")
    def add_location(name: str, venue_type: str = "casual_dining", tz: str = "UTC", ctx: dict = Depends(me)):
        need(ctx, "location.write")
        plan = billing.PLANS[db.execute("SELECT plan FROM orgs WHERE id=?", (ctx["org_id"],)).fetchone()["plan"]]
        n = db.execute("SELECT COUNT(*) c FROM locations WHERE org_id=?", (ctx["org_id"],)).fetchone()["c"]
        if n >= plan.max_locations:
            raise HTTPException(402, "plan location limit reached")
        lid = uuid.uuid4().hex
        db.execute("INSERT INTO locations(id,org_id,name,venue_type,tz) VALUES(?,?,?,?,?)", (lid, ctx["org_id"], name, venue_type, tz))
        db.commit()
        audit(ctx["org_id"], ctx["user_id"], "location.create", lid)
        return {"id": lid}

    @app.get("/locations")
    def list_locations(ctx: dict = Depends(me)):
        q, a = "SELECT id,name,venue_type,tz,staff_analytics,retention_days FROM locations WHERE org_id=?", [ctx["org_id"]]
        if ctx["role"] in rbac.LOCATION_SCOPED:
            q, a = q + " AND id=?", a + [ctx["location_id"]]
        return [dict(r) for r in db.execute(q, a)]

    @app.patch("/locations/{lid}/settings")
    def settings(lid: str, staff_analytics: str | None = None, retention_days: int | None = None, ctx: dict = Depends(me)):
        need(ctx, "location.write")
        loc_ok(ctx, lid)
        if staff_analytics is not None:
            if staff_analytics not in ("on", "anonymized", "off"):
                raise HTTPException(422, "staff_analytics must be on|anonymized|off")
            db.execute("UPDATE locations SET staff_analytics=? WHERE id=? AND org_id=?", (staff_analytics, lid, ctx["org_id"]))
        if retention_days is not None:
            plan = billing.PLANS[db.execute("SELECT plan FROM orgs WHERE id=?", (ctx["org_id"],)).fetchone()["plan"]]
            if not 1 <= retention_days <= plan.max_retention_days:
                raise HTTPException(402, f"retention limited to {plan.max_retention_days} days on this plan")
            db.execute("UPDATE locations SET retention_days=? WHERE id=? AND org_id=?", (retention_days, lid, ctx["org_id"]))
        db.commit()
        audit(ctx["org_id"], ctx["user_id"], "location.settings", lid)
        return {"ok": True}

    @app.post("/cameras")
    def add_camera(location_id: str, name: str, url: str, ctx: dict = Depends(me)):
        need(ctx, "camera.write")
        loc_ok(ctx, location_id)
        plan = billing.PLANS[db.execute("SELECT plan FROM orgs WHERE id=?", (ctx["org_id"],)).fetchone()["plan"]]
        n = db.execute("SELECT COUNT(*) c FROM cameras WHERE org_id=?", (ctx["org_id"],)).fetchone()["c"]
        if n >= plan.max_cameras:
            raise HTTPException(402, "plan camera limit reached")
        cid = uuid.uuid4().hex
        db.execute("INSERT INTO cameras(id,org_id,location_id,name,url_enc) VALUES(?,?,?,?,?)", (cid, ctx["org_id"], location_id, name, vault.seal(url)))
        db.commit()
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
        code = f"{int.from_bytes(security.os.urandom(4), 'big') % 10**8:08d}"
        db.execute("INSERT INTO pairing VALUES(?,?,?,?)", (security.digest(code), ctx["org_id"], location_id, now() + 900))
        db.commit()
        return {"code": code, "expires_in_s": 900}

    @app.post("/edge/pair")
    def edge_pair(code: str):
        r = db.execute("SELECT * FROM pairing WHERE code_hash=?", (security.digest(code),)).fetchone()
        if not r or r["expires"] < now():
            raise HTTPException(400, "invalid or expired code")
        db.execute("DELETE FROM pairing WHERE code_hash=?", (r["code_hash"],))  # single use
        tok, did = security.new_token(), uuid.uuid4().hex
        db.execute("INSERT INTO devices(id,org_id,location_id,token_hash) VALUES(?,?,?,?)", (did, r["org_id"], r["location_id"], security.digest(tok)))
        db.commit()
        return {"device_id": did, "token": tok}

    def device(authorization: str = Header(default="")) -> dict:
        d = db.execute("SELECT * FROM devices WHERE token_hash=?", (security.digest(authorization.removeprefix("Bearer ").strip()),)).fetchone()
        if not d:
            raise HTTPException(401, "unknown device")
        return dict(d)

    class EventIn(BaseModel):
        event_id: str
        t: float
        table_id: str
        kind: str
        detail: dict = {}

    @app.post("/edge/events")
    def ingest(events: list[EventIn], d: dict = Depends(device)):
        """Idempotent: replaying the same batch after an outage never duplicates events."""
        if len(events) > 1000:
            raise HTTPException(413, "batch too large")
        new = 0
        for e in events:
            cur = db.execute("INSERT OR IGNORE INTO events VALUES(?,?,?,?,?,?,?)", (d["org_id"], d["location_id"], e.event_id, e.t, e.table_id, e.kind, json.dumps(e.detail)))
            new += cur.rowcount
        db.execute("UPDATE devices SET last_seen=? WHERE id=?", (now(), d["id"]))
        db.commit()
        return {"accepted": new, "duplicates": len(events) - new}

    @app.post("/edge/heartbeat")
    def heartbeat(health: dict, version: str = "", d: dict = Depends(device)):
        db.execute("UPDATE devices SET last_seen=?, version=?, health=? WHERE id=?", (now(), version, json.dumps(health), d["id"]))
        db.commit()
        return {"ok": True}

    @app.get("/devices")
    def devices(ctx: dict = Depends(me)):
        """Fleet/support view: health only, no video, no credentials."""
        need(ctx, "camera.write")
        return [dict(r) for r in db.execute("SELECT id,location_id,last_seen,version,health FROM devices WHERE org_id=?", (ctx["org_id"],))]

    # ---- events, export, analytics ----------------------------------------------------------
    def fetch_events(ctx: dict, location_id: str, since: float = 0) -> list[dict]:
        loc_ok(ctx, location_id)
        if rbac.can(ctx["role"], "events.read"):
            own = False
        elif rbac.can(ctx["role"], "events.read.own_section"):
            own = True
        else:
            raise HTTPException(403, "missing permission events.read")
        rows = db.execute("SELECT event_id,t,table_id,kind,detail FROM events WHERE org_id=? AND location_id=? AND t>=? ORDER BY t", (ctx["org_id"], location_id, since)).fetchall()
        res = [dict(r, detail=json.loads(r["detail"])) for r in rows]
        if own:
            res = [r for r in res if r["detail"].get("section") and r["detail"]["section"] == ctx["section"]]
        return res

    @app.get("/events")
    def events_list(location_id: str, since: float = 0, ctx: dict = Depends(me)):
        return fetch_events(ctx, location_id, since)

    @app.get("/export/events.csv", response_class=PlainTextResponse)
    def export(location_id: str, ctx: dict = Depends(me)):
        need(ctx, "export")
        rows = fetch_events(ctx, location_id)
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["event_id", "t", "table_id", "kind", "detail"])
        for r in rows:
            w.writerow([r["event_id"], r["t"], r["table_id"], r["kind"], json.dumps(r["detail"])])
        audit(ctx["org_id"], ctx["user_id"], "export", location_id)
        return buf.getvalue()

    @app.get("/analytics/staff-greet-times")
    def staff_greets(location_id: str, ctx: dict = Depends(me)):
        need(ctx, "analytics.staff")
        loc_ok(ctx, location_id)
        mode = db.execute("SELECT staff_analytics FROM locations WHERE id=? AND org_id=?", (location_id, ctx["org_id"])).fetchone()["staff_analytics"]
        if mode == "off":
            raise HTTPException(403, "staff analytics disabled for this location")
        from ..analytics import greet_times
        from ..table import Event
        evs = [Event(r["t"], r["table_id"], r["kind"], r["detail"]) for r in fetch_events(ctx, location_id)]
        g = greet_times(evs)
        return {"mode": mode, "n": len(g), "median_s": sorted(g)[len(g) // 2] if g else None,
                "note": "Team-level only; individual staff are never named in anonymized mode."}

    # ---- corrections & data rights ----------------------------------------------------------
    @app.post("/corrections")
    def correction(location_id: str, kind: str, payload: dict, ctx: dict = Depends(me)):
        need(ctx, "corrections.write")
        loc_ok(ctx, location_id)
        db.execute("INSERT INTO corrections(org_id,location_id,kind,payload,consent_training,t) VALUES(?,?,?,?,0,?)", (ctx["org_id"], location_id, kind, json.dumps(payload), now()))
        db.commit()
        return {"ok": True}  # never used for model training unless the org opts in later

    @app.get("/audit")
    def audit_log(ctx: dict = Depends(me)):
        need(ctx, "audit.read")
        return [dict(r) for r in db.execute("SELECT user_id,action,target,t FROM audit WHERE org_id=? ORDER BY id DESC LIMIT 500", (ctx["org_id"],))]

    @app.delete("/org/data")
    def delete_data(confirm: str, ctx: dict = Depends(me)):
        need(ctx, "data.delete")
        if confirm != "DELETE":
            raise HTTPException(422, "pass confirm=DELETE")
        for t in ("events", "cameras", "devices", "pairing", "corrections", "webhooks", "locations", "invites"):
            db.execute(f"DELETE FROM {t} WHERE org_id=?", (ctx["org_id"],))
        db.commit()
        audit(ctx["org_id"], ctx["user_id"], "org.data_deleted")
        return {"ok": True}

    @app.post("/billing/plan")
    def set_plan(plan: str, ctx: dict = Depends(me)):
        need(ctx, "billing")
        if plan not in billing.PLANS:
            raise HTTPException(422, "unknown plan")
        db.execute("UPDATE orgs SET plan=? WHERE id=?", (plan, ctx["org_id"]))
        db.commit()
        bill.set_plan(ctx["org_id"], plan)
        return {"plan": plan}

    return app
