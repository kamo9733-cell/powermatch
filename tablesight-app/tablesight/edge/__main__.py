"""Minimal service entrypoint: heartbeat loop only. Camera pipeline wiring is not done yet."""
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

from tablesight.edge.agent import Outbox
from tablesight.edge.health import Heartbeat
from tablesight.edge.pairing import load_credentials


def beat(creds: dict, hb: Heartbeat, outbox: Outbox, post_json, now: float) -> int:
    url = f"{creds['api'].rstrip('/')}/edge/heartbeat?version={hb.version}"
    return post_json(url, hb.payload(now, len(outbox)), creds["token"])


def _post_json(url: str, body: dict, token: str) -> int:  # pragma: no cover - network
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST", headers={
        "Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return r.status


def main() -> int:  # pragma: no cover - loop
    state = Path(os.environ.get("TABLESIGHT_STATE", "/var/lib/tablesight-edge"))
    creds = load_credentials(state / "device.json")
    ob, hb = Outbox(str(state / "outbox.db")), Heartbeat(os.environ.get("TABLESIGHT_VERSION", "0.0.0"))
    while True:
        try:
            beat(creds, hb, ob, _post_json, time.time())
        except Exception as e:  # noqa: BLE001 - keep beating through any failure
            print("heartbeat failed:", type(e).__name__, file=sys.stderr)
        time.sleep(60)


if __name__ == "__main__":
    sys.exit(main())
