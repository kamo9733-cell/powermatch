"""Auth primitives from the stdlib + cryptography (Apache-2.0/BSD): scrypt, TOTP, Fernet, rate limits."""
import base64
import hashlib
import hmac
import os
import secrets
import struct
import time
from collections import defaultdict, deque

from cryptography.fernet import Fernet


def hash_password(pw: str) -> str:
    salt = os.urandom(16)
    h = hashlib.scrypt(pw.encode(), salt=salt, n=2**14, r=8, p=1)
    return f"scrypt${salt.hex()}${h.hex()}"


def verify_password(pw: str, stored: str) -> bool:
    _, salt, h = stored.split("$")
    cand = hashlib.scrypt(pw.encode(), salt=bytes.fromhex(salt), n=2**14, r=8, p=1)
    return hmac.compare_digest(cand.hex(), h)


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
    now = at if at is not None else time.time()
    return any(hmac.compare_digest(totp(secret, now + d * 30), code) for d in (-1, 0, 1))


class Vault:
    """Encrypts camera credentials at rest. Key comes from env/secret store, never the repo."""

    def __init__(self, key: bytes | None = None):
        self._f = Fernet(key or Fernet.generate_key())

    def seal(self, s: str) -> bytes:
        return self._f.encrypt(s.encode())

    def open(self, b: bytes) -> str:
        return self._f.decrypt(b).decode()


class RateLimiter:
    def __init__(self, limit: int, per_s: float):
        self.limit, self.per_s = limit, per_s
        self._hits: dict[str, deque] = defaultdict(deque)

    def allow(self, key: str, now: float | None = None) -> bool:
        now = now if now is not None else time.time()
        q = self._hits[key]
        while q and now - q[0] > self.per_s:
            q.popleft()
        if len(q) >= self.limit:
            return False
        q.append(now)
        return True
