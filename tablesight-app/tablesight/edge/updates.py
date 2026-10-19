"""Signed updates: Ed25519 (via `cryptography`) over a canonical manifest; anti-downgrade; hash check.

Manifest: {"version": "1.2.3", "sha256": "<hex of artifact>", "url": "..."}; envelope is
{"manifest": {...}, "signature": "<hex>"}. Signature covers canonical JSON (sorted keys, compact).
The public key is baked into the install; the private key never leaves the release machine.
"""
import hashlib
import hmac
import json
import re

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey


class UpdateRejected(Exception):
    pass


def canonical(manifest: dict) -> bytes:
    return json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()


def parse_version(v: str) -> tuple[int, ...]:
    if not isinstance(v, str) or not re.fullmatch(r"\d+(\.\d+){0,3}", v):
        raise UpdateRejected(f"bad version {v!r}")
    return tuple(int(x) for x in v.split("."))


def sign(manifest: dict, key: Ed25519PrivateKey) -> dict:  # release tooling + tests
    return {"manifest": manifest, "signature": key.sign(canonical(manifest)).hex()}


def verify(envelope: dict, public_key: Ed25519PublicKey, current_version: str) -> dict:
    try:
        manifest, sig = envelope["manifest"], bytes.fromhex(envelope["signature"])
    except (KeyError, TypeError, ValueError):
        raise UpdateRejected("unsigned or malformed envelope") from None
    try:
        public_key.verify(sig, canonical(manifest))
    except InvalidSignature:
        raise UpdateRejected("signature invalid") from None
    if parse_version(manifest.get("version")) <= parse_version(current_version):
        raise UpdateRejected("downgrade or replay of same version")
    if not re.fullmatch(r"[0-9a-f]{64}", str(manifest.get("sha256", ""))):
        raise UpdateRejected("manifest lacks sha256")
    return manifest


def verify_artifact(manifest: dict, blob: bytes) -> None:
    if not hmac.compare_digest(hashlib.sha256(blob).hexdigest(), manifest["sha256"]):
        raise UpdateRejected("artifact hash mismatch")
