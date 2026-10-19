"""Boot the TableSight API + web UI in-process with DEMO data (everything is labelled 'DEMO MODE').
NOTE: the heartbeat thread below simulates a live camera box; staleness only appears with --stale.

    python scripts/seed_demo.py [--port N] [--stale] [--lang ar]

Serves the API at / and the web app at /app/. Logins (all passwords: DEMO_PASSWORD):
    owner@demo.tablesight.test   owner (settings page)
    gm@demo.tablesight.test      manager, two-step sign-in ON (code printed at start-up; rotates every 30 s)
"""
import argparse
import socket
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import uvicorn
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.testclient import TestClient

from tablesight.platform import security
from tablesight.platform.app import Outbox, create_app

DEMO_PASSWORD = "demo-password-123"
OWNER, GM = "owner@demo.tablesight.test", "gm@demo.tablesight.test"
LOCATION = "DEMO MODE - Harbour Bistro"


def _events(now: float) -> list[dict]:
    """(table, kind, minutes_ago, detail). Covers every UI state: long wait, ok, uncertain, empty, cleaning."""
    spec = [
        ("T1", "seated", 52, {"party": 4}), ("T1", "staff_visit", 31, {}), ("T1", "needs_attention", 6, {"waited": 1500}),
        ("T2", "seated", 40, {"party": 2}), ("T2", "needs_attention", 9, {"waited": 1800}),
        ("T3", "seated", 12, {"party": 6}), ("T3", "staff_visit", 4, {}),
        ("T4", "seated", 25, {"party": 3}), ("T4", "staff_visit", 14, {}),
        ("T5", "seated", 18, {"party": 2}), ("T5", "uncertain", 3, {"stale": False, "confidence": 0.3}),
        ("T6", "seated", 60, {"party": 2}), ("T6", "vacated", 20, {"dwell": 2400}), ("T6", "needs_clean", 15, {"waited": 300}),
        ("T7", "seated", 90, {"party": 2}), ("T7", "vacated", 30, {"dwell": 3600}),
        ("T8", "seated", 5, {"party": 5}),
    ]
    return [{"event_id": f"demo-{i}", "t": now - m * 60, "table_id": tb, "kind": k, "detail": d}
            for i, (tb, k, m, d) in enumerate(spec)]


WEB_CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; "
           "frame-ancestors 'none'; base-uri 'none'; form-action 'self'")


class _WebHeaders:
    """The API stamps `default-src 'none'` on every response (correct for JSON). The web assets therefore live
    OUTSIDE the API app, here as a sibling route with their own CSP. Production: serve web/ from a static host
    / reverse-proxy path with this same policy."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        async def send2(m):
            if m["type"] == "http.response.start":
                hs = [(k, v) for k, v in m["headers"] if k.lower() not in (b"content-security-policy", b"cache-control")]
                m = {**m, "headers": hs + [(b"content-security-policy", WEB_CSP.encode()), (b"cache-control", b"no-cache"),
                                           (b"x-content-type-options", b"nosniff"), (b"referrer-policy", b"no-referrer")]}
            await send(m)
        await self.app(scope, receive, send2)


def _compose(api):
    from starlette.applications import Starlette
    from starlette.routing import Mount, Route
    web = StaticFiles(directory=str(ROOT / "web"), html=True)
    outer = Starlette(routes=[
        Route("/", lambda r: RedirectResponse("/app/")),
        Mount("/app", app=_WebHeaders(web)),
        Mount("/", app=api),
    ])
    outer.state.api = api
    return outer


def build_demo(stale: bool = False):
    """Return (app, info). stale=True ages the device heartbeat so the UI shows its stale state."""
    ob = Outbox()
    api = create_app(outbox=ob)
    c = TestClient(api)

    def login(email, totp=None):
        r = c.post("/login", json={"email": email, "password": DEMO_PASSWORD, "totp": totp})
        r.raise_for_status()
        return {"Authorization": "Bearer " + r.json()["token"]}

    c.post("/signup", json={"email": OWNER, "password": DEMO_PASSWORD, "org_name": "DEMO MODE Group"}).raise_for_status()
    c.post("/verify-email", params={"token": [m for m in ob.sent if m["kind"] == "verify_email"][-1]["token"]}).raise_for_status()
    ho = login(OWNER)
    lid = c.post("/locations", params={"name": LOCATION}, headers=ho).json()["id"]
    api.state.db.execute("UPDATE locations SET demo=1 WHERE id=?", (lid,))
    c.post("/cameras", params={"location_id": lid, "name": "Dining room", "url": "rtsp://demo.invalid/stream"}, headers=ho)
    # manager with two-step sign-in
    c.post("/invites", params={"email": GM, "role": "gm", "location_id": lid}, headers=ho).raise_for_status()
    inv = [m for m in ob.sent if m["kind"] == "invite"][-1]["token"]
    c.post("/invites/accept", params={"token": inv, "password": DEMO_PASSWORD}).raise_for_status()
    hg = login(GM)
    secret = c.post("/2fa/setup", headers=hg).json()["secret"]
    # edge device + events
    code = c.post("/pairing", params={"location_id": lid}, headers=ho).json()["code"]
    dev = c.post("/edge/pair", params={"code": code}).json()
    hd = {"Authorization": "Bearer " + dev["token"]}
    now = time.time()
    c.post("/edge/events", json=_events(now), headers=hd).raise_for_status()
    c.post("/edge/heartbeat", params={"version": "demo"}, json={"fps": 12}, headers=hd).raise_for_status()
    if stale:
        api.state.db.execute("UPDATE devices SET last_seen=?", (now - 600,))
        api.state.db.commit()

    outer = _compose(api)

    if not stale:  # keep the camera box "alive" while the demo runs
        def beat():
            while True:
                time.sleep(20)
                try:
                    api.state.db.execute("UPDATE devices SET last_seen=?", (time.time(),))
                    api.state.db.commit()
                except Exception:  # noqa: BLE001
                    return
        threading.Thread(target=beat, daemon=True).start()
    info = {"owner": OWNER, "gm": GM, "password": DEMO_PASSWORD, "totp_secret": secret, "location_id": lid}
    return outer, info


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Running:
    def __init__(self, server: uvicorn.Server, thread: threading.Thread, port: int):
        self.server, self.thread, self.port = server, thread, port
        self.url = f"http://127.0.0.1:{port}"

    def stop(self):
        self.server.should_exit = True
        self.thread.join(timeout=10)


def serve(app, port: int | None = None) -> Running:
    port = port or free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    th = threading.Thread(target=server.run, daemon=True)
    th.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.1)
    return Running(server, th, port)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=0)
    ap.add_argument("--stale", action="store_true", help="demo the stale-camera state")
    ap.add_argument("--lang", default="en")
    a = ap.parse_args()
    app, info = build_demo(stale=a.stale)
    run = serve(app, a.port)
    print(f"DEMO MODE running: {run.url}/app/?lang={a.lang}")
    print(f"  owner: {info['owner']} / {info['password']}")
    print(f"  manager (2FA): {info['gm']} / {info['password']}  current code: {security.totp(info['totp_secret'])}")
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        run.stop()


if __name__ == "__main__":
    main()
