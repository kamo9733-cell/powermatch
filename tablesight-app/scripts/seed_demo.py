"""Boot the TableSight API + web UI in-process with DEMO data (everything is labelled 'DEMO MODE').

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

import uvicorn  # noqa: E402
from fastapi.responses import RedirectResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from tablesight.platform import security  # noqa: E402
from tablesight.platform.app import Outbox, create_app  # noqa: E402

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


def build_demo(stale: bool = False):
    """Return (app, info). stale=True ages the device heartbeat so the UI shows its stale state."""
    ob = Outbox()
    app = create_app(outbox=ob)
    c = TestClient(app)

    def login(email, totp=None):
        r = c.post("/login", json={"email": email, "password": DEMO_PASSWORD, "totp": totp})
        r.raise_for_status()
        return {"Authorization": "Bearer " + r.json()["token"]}

    c.post("/signup", json={"email": OWNER, "password": DEMO_PASSWORD, "org_name": "DEMO MODE Group"}).raise_for_status()
    c.post("/verify-email", params={"token": [m for m in ob.sent if m["kind"] == "verify_email"][-1]["token"]}).raise_for_status()
    ho = login(OWNER)
    lid = c.post("/locations", params={"name": LOCATION}, headers=ho).json()["id"]
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
        app.state.db.execute("UPDATE devices SET last_seen=?", (now - 600,))
        app.state.db.commit()

    web = ROOT / "web"
    app.mount("/app", StaticFiles(directory=str(web), html=True), name="web")
    app.add_api_route("/", lambda: RedirectResponse("/app/"), include_in_schema=False)

    if not stale:  # keep the camera box "alive" while the demo runs
        def beat():
            while True:
                time.sleep(20)
                try:
                    app.state.db.execute("UPDATE devices SET last_seen=?", (time.time(),))
                    app.state.db.commit()
                except Exception:
                    return
        threading.Thread(target=beat, daemon=True).start()
    info = {"owner": OWNER, "gm": GM, "password": DEMO_PASSWORD, "totp_secret": secret, "location_id": lid}
    return app, info


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
