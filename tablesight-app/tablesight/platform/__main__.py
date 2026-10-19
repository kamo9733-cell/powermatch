"""Run: python -m tablesight.platform
env: TABLESIGHT_DB, TABLESIGHT_VAULT_KEY, PORT, HOST (default 0.0.0.0 because deploy/Dockerfile relies on it; bind 127.0.0.1 behind a TLS proxy),
     TABLESIGHT_ALLOW_SELF_SERVE_PLAN=1 (dev only: lets an owner upgrade their own plan without paying).
Uvicorn's access log is OFF: legacy clients may still pass tokens/passwords in query strings."""
import os

import uvicorn

from .app import create_app

key = os.environ.get("TABLESIGHT_VAULT_KEY")
if not key:
    raise SystemExit("Set TABLESIGHT_VAULT_KEY (generate: python -c 'from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())')")
app = create_app(os.environ.get("TABLESIGHT_DB", "tablesight.db"), key.encode(),
                 allow_self_serve_plan=os.environ.get("TABLESIGHT_ALLOW_SELF_SERVE_PLAN") == "1")
import threading
import time


def _purge_loop():
    while True:
        try:
            app.state.purge()
        except Exception as e:  # noqa: BLE001  # never let housekeeping kill the API
            print("retention purge failed:", e)
        time.sleep(3600)


threading.Thread(target=_purge_loop, daemon=True).start()
uvicorn.run(app, host=os.environ.get("HOST", "0.0.0.0"), port=int(os.environ.get("PORT", "8080")), access_log=False)
