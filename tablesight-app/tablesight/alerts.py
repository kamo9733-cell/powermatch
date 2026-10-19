"""Alert policy: fatigue control sits between events and people's phones."""
from dataclasses import dataclass, field

from .table import Event
from .templates import VenueTemplate


@dataclass
class AlertEngine:
    tpl: VenueTemplate
    rush_tables_threshold: int = 6   # when this many tables are flagged at once, batch instead
    min_gap_s: float = 90            # per-recipient spacing
    sent: list[dict] = field(default_factory=list)
    _count: dict[str, int] = field(default_factory=dict)
    _last_sent: float = -1e9
    _open: set[str] = field(default_factory=set)

    def process(self, ev: Event, now: float | None = None) -> dict | None:
        if ev.kind == "staff_visit" or ev.kind == "vacated":
            self._open.discard(ev.table)
            return None
        if ev.kind != "needs_attention":
            return None
        if self._count.get(ev.table, 0) >= self.tpl.max_alerts_per_table:
            return None
        if ev.t - self._last_sent < self.min_gap_s:
            return None  # batched into the next one; avoids rush spam
        self._open.add(ev.table)
        self._count[ev.table] = self._count.get(ev.table, 0) + 1
        self._last_sent = ev.t
        alert = {"t": ev.t, "table": ev.table, "waited_s": ev.detail["waited"],
                 "first_visit": ev.detail["first_visit"], "rush": len(self._open) >= self.rush_tables_threshold,
                 "text": f"Table {ev.table}: no check-in for {int(ev.detail['waited'] // 60)} min"}
        self.sent.append(alert)
        return alert
