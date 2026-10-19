"""Pairing client: exchange the dashboard code for a device token (POST /edge/pair?code=...)."""
import json
import os
from collections.abc import Callable
from pathlib import Path

# post(url) -> (status, json_body). Injected; default uses urllib.
Post = Callable[[str], tuple[int, dict]]


class PairingError(RuntimeError):
    pass


def urllib_post(url: str, timeout: float = 15) -> tuple[int, dict]:  # pragma: no cover - network
    import urllib.error
    import urllib.request
    req = urllib.request.Request(url, method="POST", data=b"")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, {}


def write_secret(path: Path, text: str) -> None:
    """Atomic write, created 0600 from the start (never briefly world-readable)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(text)
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def pair(api: str, code: str, store: Path, post: Post = urllib_post) -> dict:
    from urllib.parse import quote
    if not api.startswith("https://") and not api.startswith("http://localhost"):
        raise PairingError("API url must be https:// (token would travel in clear text)")
    status, body = post(f"{api.rstrip('/')}/edge/pair?code={quote(code, safe='')}")
    if status != 200 or "token" not in body or "device_id" not in body:
        raise PairingError(f"pairing refused (HTTP {status}); code may be expired or used")
    write_secret(store, json.dumps({"api": api, "device_id": body["device_id"], "token": body["token"]}))
    return {"device_id": body["device_id"]}


def load_credentials(store: Path) -> dict:
    if store.stat().st_mode & 0o077:
        raise PairingError(f"{store} is accessible by other users; refusing to use it")
    return json.loads(store.read_text())
