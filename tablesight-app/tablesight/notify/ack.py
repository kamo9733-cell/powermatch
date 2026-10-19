"""Acknowledgement workflow: one record per (alert, recipient) delivery.

SENT -> DELIVERED -> ACKED -> RESOLVED, with EXPIRED as the other terminal state.
Updates are idempotent and tolerate out-of-order receipts: repeating a transition, replaying an
event id, or a late/backwards one (e.g. DELIVERED after ACKED) is ignored and returns False.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class DeliveryState(str, Enum):
    SENT = "sent"
    DELIVERED = "delivered"
    ACKED = "acked"
    RESOLVED = "resolved"
    EXPIRED = "expired"


S = DeliveryState
ALLOWED: dict[DeliveryState, frozenset[DeliveryState]] = {
    S.SENT: frozenset({S.DELIVERED, S.ACKED, S.RESOLVED, S.EXPIRED}),
    S.DELIVERED: frozenset({S.ACKED, S.RESOLVED, S.EXPIRED}),
    S.ACKED: frozenset({S.RESOLVED}),
    S.RESOLVED: frozenset(),
    S.EXPIRED: frozenset(),
}


@dataclass
class DeliveryRecord:
    delivery_id: str
    alert_id: str
    recipient: str
    state: DeliveryState = S.SENT
    history: list[tuple[DeliveryState, float]] = field(default_factory=list)
    _events: set[str] = field(default_factory=set)


class AckTracker:
    def __init__(self) -> None:
        self._records: dict[str, DeliveryRecord] = {}

    def register(self, delivery_id: str, alert_id: str, recipient: str, t: float) -> DeliveryRecord:
        """Idempotent: re-registering an existing delivery returns it untouched."""
        rec = self._records.get(delivery_id)
        if rec is None:
            rec = DeliveryRecord(delivery_id, alert_id, recipient, S.SENT, [(S.SENT, t)])
            self._records[delivery_id] = rec
        return rec

    def get(self, delivery_id: str) -> DeliveryRecord | None:
        return self._records.get(delivery_id)

    def for_alert(self, alert_id: str) -> list[DeliveryRecord]:
        return [r for r in self._records.values() if r.alert_id == alert_id]

    def apply(self, delivery_id: str, to: DeliveryState, t: float, event_id: str | None = None) -> bool:
        """Returns True only if the state actually changed."""
        rec = self._records.get(delivery_id)
        if rec is None:
            return False
        if event_id is not None:
            if event_id in rec._events:
                return False
            rec._events.add(event_id)
        if to not in ALLOWED[rec.state]:
            return False
        rec.state = to
        rec.history.append((to, t))
        return True
