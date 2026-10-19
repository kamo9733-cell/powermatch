"""Run: python -m tablesight.platform  (env: TABLESIGHT_DB, TABLESIGHT_VAULT_KEY, PORT)."""
import os

import uvicorn

from .app import create_app

key = os.environ.get("TABLESIGHT_VAULT_KEY")
if not key:
    raise SystemExit("Set TABLESIGHT_VAULT_KEY (generate: python -c 'from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())')")
app = create_app(os.environ.get("TABLESIGHT_DB", "tablesight.db"), key.encode())
uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))  # noqa: S104 behind reverse proxy
