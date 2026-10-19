"""Alert policy: fatigue control sits between events and people's phones."""
from dataclasses import dataclass, field

from .table import Event
from .templates import VenueTemplate


@dataclass
class AlertEngine:
    tpl: VenueTemplate
    min_gap_s: float = 90  # per-recipient spacing
    sent: list[dict] = field(default_factory=list)
    _count: dict[str, int] = field(default_factory=dict)
    _last_sent: float = -1e9
    _held: dict[str, Event] = field(default_factory=dict)

    def process(self, ev: Event) -> dict | None:
        if ev.kind in ("seated", "vacated"):
            self._count.pop(ev.table, None)  # the per-table cap is per visit, not for the table's lifetime
        if ev.kind in ("staff_visit", "vacated"):
            self._held.pop(ev.table, None)  # resolved while waiting: never send stale alerts
            return None
        if ev.kind != "needs_attention":
            return None
        if self._count.get(ev.table, 0) >= self.tpl.max_alerts_per_table:
            return None
        if 0 <= ev.t - self._last_sent < self.min_gap_s:  # negative = clock jumped back: don't hold forever
            self._held[ev.table] = ev  # held for the digest, never lost
            return None
        return self._send([ev], ev.t)

    def flush(self, now: float) -> dict | None:
        """Emit one digest for tables held back during a rush."""
        if not self._held or 0 <= now - self._last_sent < self.min_gap_s:
            return None
        evs = list(self._held.values())
        self._held.clear()
        return self._send(evs, now)

    def _send(self, evs: list[Event], t: float) -> dict:
        for e in evs:
            self._count[e.table] = self._count.get(e.table, 0) + 1
        self._last_sent = t
        if len(evs) == 1:
            e = evs[0]
            text = f"Table {e.table}: no check-in for {int(e.detail['waited'] // 60)} min"
        else:
            text = f"{len(evs)} tables need a check-in: " + ", ".join(e.table for e in evs)
        alert = {"t": t, "tables": [e.table for e in evs], "digest": len(evs) > 1, "text": text}
        self.sent.append(alert)
        return alert
