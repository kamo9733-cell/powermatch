"""Signed webhook: HMAC-SHA256 over "<timestamp>.<body>" with replay protection.

Headers sent:  X-Tablesight-Timestamp (unix seconds), X-Tablesight-Signature ("v1=<hex>"),
X-Tablesight-Delivery (stable per alert+recipient, so receivers can de-duplicate retries).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

from .base import DeliveryResult, HttpRequest, HttpTransport, Message, post

TS_HEADER = "X-Tablesight-Timestamp"
SIG_HEADER = "X-Tablesight-Signature"
DELIVERY_HEADER = "X-Tablesight-Delivery"
DEFAULT_TOLERANCE_S = 300


def sign(secret: bytes, timestamp: int, body: bytes) -> str:
    mac = hmac.new(secret, f"{timestamp}.".encode() + body, hashlib.sha256)
    return "v1=" + mac.hexdigest()


@dataclass
class WebhookNotifier:
    url: str
    secret: bytes
    transport: HttpTransport
    clock: Callable[[], float] = time.time
    channel: str = "webhook"

    def send(self, msg: Message) -> DeliveryResult:
        body = json.dumps(
            {
                "alert_id": msg.alert_id,
                "recipient": msg.recipient,
                "title": msg.title,
                "body": msg.body,
                "priority": msg.priority,
                "tables": list(msg.tables),
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        ts = int(self.clock())
        headers = {
            "Content-Type": "application/json",
            TS_HEADER: str(ts),
            SIG_HEADER: sign(self.secret, ts, body),
            DELIVERY_HEADER: f"{msg.alert_id}:{msg.recipient}",
        }
        return post(self.channel, self.transport, HttpRequest("POST", self.url, headers, body))


@dataclass
class WebhookVerifier:
    """Receiver side: rejects bad signatures, stale/future timestamps and replays."""

    secret: bytes
    tolerance_s: int = DEFAULT_TOLERANCE_S
    _seen: dict[str, float] = field(default_factory=dict)

    def verify(self, headers: Mapping[str, str], body: bytes, now: float) -> bool:
        h = {k.lower(): v for k, v in headers.items()}
        try:
            ts = int(h[TS_HEADER.lower()])
            sig = h[SIG_HEADER.lower()]
        except (KeyError, ValueError):
            return False
        if abs(now - ts) > self.tolerance_s:
            return False
        if not hmac.compare_digest(sig, sign(self.secret, ts, body)):
            return False
        # Replay: an identical (timestamp, signature) pair is only accepted once per window.
        self._seen = {k: v for k, v in self._seen.items() if now - v <= self.tolerance_s}
        if sig in self._seen:
            return False
        self._seen[sig] = now
        return True
