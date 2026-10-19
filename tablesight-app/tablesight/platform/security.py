"""Auth primitives from the stdlib + cryptography (Apache-2.0/BSD): scrypt, TOTP, Fernet, rate limits."""
import base64
import hashlib
import hmac
import os
import secrets
import struct
import threading
import time
from collections import defaultdict, deque

from cryptography.fernet import Fernet


def hash_password(pw: str) -> str:
    salt = os.urandom(16)
    h = hashlib.scrypt(pw.encode(), salt=salt, n=2**14, r=8, p=1)
    return f"scrypt${salt.hex()}${h.hex()}"


def verify_password(pw: str, stored: str) -> bool:
    try:
        _, salt, h = stored.split("$")
        bytes.fromhex(salt)
    except ValueError:
        return False
    cand = hashlib.scrypt(pw.encode(), salt=bytes.fromhex(salt), n=2**14, r=8, p=1)
    return hmac.compare_digest(cand.hex(), h)


# Verified once per failed lookup so "no such user" costs the same single scrypt as "wrong password".
DUMMY_HASH = hash_password("tablesight-dummy-password")

# No 0/O/1/I/L/U: codes are typed by a human on an edge box. 31 symbols x 10 chars ~ 49.5 bits.
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTVWXYZ23456789"


def new_pairing_code() -> str:
    raw = "".join(secrets.choice(CODE_ALPHABET) for _ in range(10))
    return f"{raw[:5]}-{raw[5:]}"


def normalize_code(code: str) -> str:
    return code.strip().upper().replace("-", "").replace(" ", "")


def bearer(header: str) -> str:
    """Token from an `Authorization: Bearer <t>` header; '' when absent or another scheme."""
    scheme, _, tok = header.partition(" ")
    return tok.strip() if scheme.lower() == "bearer" else ""


def csv_safe(v) -> str:
    """Neutralise spreadsheet formula injection: a cell starting = + - @ TAB CR would be evaluated."""
    s = str(v)
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s


def new_token() -> str:
    return secrets.token_urlsafe(32)


def digest(token: str) -> str:
    """Tokens are stored hashed: a DB leak must not leak live sessions."""
    return hashlib.sha256(token.encode()).hexdigest()


def new_totp_secret() -> str:
    return base64.b32encode(os.urandom(20)).decode()


def totp(secret: str, at: float | None = None, step: int = 30, digits: int = 6) -> str:
    counter = int((at if at is not None else time.time()) // step)
    mac = hmac.new(base64.b32decode(secret), struct.pack(">Q", counter), "sha1").digest()
    o = mac[-1] & 0xF
    code = (struct.unpack(">I", mac[o:o + 4])[0] & 0x7FFFFFFF) % 10**digits
    return str(code).zfill(digits)


def verify_totp(secret: str, code: str, at: float | None = None) -> bool:
    return totp_step(secret, code, at) is not None


def totp_step(secret: str, code: str, at: float | None = None) -> int | None:
    """Counter value the code matches (window +-1 step) or None; callers store it to stop replay."""
    now = at if at is not None else time.time()
    hit = None
    for d in (-1, 0, 1):  # no early exit: constant work
        if hmac.compare_digest(totp(secret, now + d * 30), code):
            hit = int((now + d * 30) // 30)
    return hit


class Vault:
    """Encrypts camera credentials at rest. Key comes from env/secret store, never the repo."""

    def __init__(self, key: bytes | None = None):
        self._f = Fernet(key or Fernet.generate_key())

    def seal(self, s: str) -> bytes:
        return self._f.encrypt(s.encode())

    def open(self, b: bytes) -> str:
        return self._f.decrypt(b).decode()


class RateLimiter:
    """Sliding window. Thread-safe; idle keys are dropped and the key table is capped so an attacker
    spraying random emails/IPs cannot grow memory without bound."""

    MAX_KEYS = 50_000

    def __init__(self, limit: int, per_s: float):
        self.limit, self.per_s = limit, per_s
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str, now: float | None = None) -> bool:
        now = now if now is not None else time.time()
        with self._lock:
            if key not in self._hits and len(self._hits) >= self.MAX_KEYS:
                self._sweep(now)
                if len(self._hits) >= self.MAX_KEYS:
                    return False  # fail closed under a key-flooding attack
            q = self._hits[key]
            while q and now - q[0] > self.per_s:
                q.popleft()
            if len(q) >= self.limit:
                return False
            q.append(now)
            return True

    def blocked(self, key: str, now: float | None = None) -> bool:
        """Peek: is `key` at its limit? Records nothing (use with record() to throttle failures only)."""
        now = now if now is not None else time.time()
        with self._lock:
            q = self._hits.get(key)
            if q is None:
                return False
            while q and now - q[0] > self.per_s:
                q.popleft()
            return len(q) >= self.limit

    def record(self, key: str, now: float | None = None) -> None:
        now = now if now is not None else time.time()
        with self._lock:
            if key in self._hits or len(self._hits) < self.MAX_KEYS:
                self._hits[key].append(now)

    def _sweep(self, now: float) -> None:
        for k in [k for k, q in self._hits.items() if not q or now - q[-1] > self.per_s]:
            del self._hits[k]
