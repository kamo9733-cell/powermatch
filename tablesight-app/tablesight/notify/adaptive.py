"""Adaptive thresholds and the per-recipient alerts-per-hour budget.

Rules (bounds make them safe to tune):
  * The venue template's `greet_alert_s` is a hard FLOOR: we may wait longer, never alert sooner.
  * Rush (busy floor): raise the threshold and switch to digest mode, spaced further apart.
  * Quiet: stay at the floor (tighter than the rush/dinner baseline, never below the template).
  * The multiplier is capped at MAX_MULT so a long rush cannot silence neglect alerts for good.
  * Venues where table-service alerts make no sense (greet_alert_s == 0) stay "off".
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass

from ..templates import VenueTemplate

MAX_MULT = 2.0
DAYPART_MULT = {"breakfast": 1.0, "lunch": 1.1, "afternoon": 1.0, "dinner": 1.15, "late": 1.0}
BUSY_MULT = {"quiet": 0.9, "normal": 1.0, "rush": 1.25}
RUSH_GAP_MULT = 3.0
QUIET_BELOW = 0.35
RUSH_FROM = 0.80


def daypart(hour: int) -> str:
    """Local hour 0-23 -> daypart name."""
    h = hour % 24
    if 6 <= h < 11:
        return "breakfast"
    if 11 <= h < 15:
        return "lunch"
    if 15 <= h < 17:
        return "afternoon"
    if 17 <= h < 22:
        return "dinner"
    return "late"


def busyness(occupancy: float) -> str:
    """occupancy = seated tables / total tables, 0..1."""
    if occupancy >= RUSH_FROM:
        return "rush"
    return "quiet" if occupancy < QUIET_BELOW else "normal"


@dataclass(frozen=True)
class Adaptive:
    threshold_s: float | None
    mode: str  # live | digest | off
    min_gap_s: float
    daypart: str
    busyness: str


def adapt(tpl: VenueTemplate, hour: int, occupancy: float, base_gap_s: float = 90) -> Adaptive:
    dp, busy = daypart(hour), busyness(occupancy)
    if not tpl.table_service or tpl.greet_alert_s <= 0:
        return Adaptive(None, "off", base_gap_s, dp, busy)
    floor = float(tpl.greet_alert_s)
    mult = DAYPART_MULT[dp] * BUSY_MULT[busy]
    threshold = min(max(floor, floor * mult), floor * MAX_MULT)
    rush = busy == "rush"
    gap = base_gap_s * (RUSH_GAP_MULT if rush else 1.0)
    return Adaptive(threshold, "digest" if rush else "live", max(gap, base_gap_s), dp, busy)


class AlertBudget:
    """Rolling-window cap on notifications per recipient (default 6/hour, QUALITY_TARGETS.md)."""

    def __init__(self, max_per_hour: int = 6, window_s: float = 3600.0) -> None:
        self.max = max_per_hour
        self.window_s = window_s
        self._log: dict[str, deque[float]] = defaultdict(deque)

    def count(self, who: str, t: float) -> int:
        q = self._log[who]
        while q and q[0] <= t - self.window_s:
            q.popleft()
        return len(q)

    def allow(self, who: str, t: float) -> bool:
        return self.count(who, t) < self.max

    def record(self, who: str, t: float) -> None:
        self._log[who].append(t)
