"""Escalation: server -> section lead -> manager, with ack timeouts, snooze and quiet hours.

Hard rules:
  * Off-shift staff are NEVER notified (checked at the moment of every dispatch).
  * Do-not-disturb windows and snoozes are respected the same way; there is no override.
  * Every notification counts against the per-recipient hourly budget when one is supplied.
  * Starting the same alert id twice is a no-op; acking twice is harmless.
Time is float seconds (UTC epoch or sim time), like the rest of the core.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from .notify.ack import AckTracker, DeliveryState
from .notify.adaptive import AlertBudget

LEVELS = ("server", "section_lead", "manager")  # role at each escalation level


@dataclass(frozen=True)
class Staff:
    id: str
    name: str
    role: str  # one of LEVELS
    section: str | None = None  # managers cover every section
    tz: str = "UTC"
    dnd: tuple[tuple[int, int], ...] = ()  # daily local (start_min, end_min); may wrap midnight


@dataclass(frozen=True)
class Shift:
    staff_id: str
    start: float
    end: float


class ShiftSchedule:
    def __init__(self, shifts: list[Shift] | None = None) -> None:
        self._shifts: dict[str, list[Shift]] = {}
        for s in shifts or []:
            self.add(s)

    def add(self, shift: Shift) -> None:
        if shift.end <= shift.start:
            raise ValueError("shift must end after it starts")
        self._shifts.setdefault(shift.staff_id, []).append(shift)

    def on_shift(self, staff_id: str, t: float) -> bool:
        return any(s.start <= t < s.end for s in self._shifts.get(staff_id, ()))


def in_dnd(staff: Staff, t: float) -> bool:
    local = datetime.fromtimestamp(t, UTC).astimezone(ZoneInfo(staff.tz))
    m = local.hour * 60 + local.minute
    for a, b in staff.dnd:
        if (a <= m < b) if a <= b else (m >= a or m < b):
            return True
    return False


@dataclass
class EscalationPolicy:
    ack_timeout_s: tuple[float, float, float] = (120.0, 180.0, 240.0)
    max_snooze_s: float = 900.0  # a snooze can never silence someone for more than this
    max_pending_s: float = 1800.0  # an alert nobody can take expires, visibly, after this


@dataclass(frozen=True)
class Dispatch:
    alert_id: str
    staff_id: str
    role: str
    level: int
    t: float
    section: str
    tables: tuple[str, ...]


@dataclass
class _Alert:
    id: str
    section: str
    tables: tuple[str, ...]
    created: float
    status: str = "pending"  # pending | acked | resolved | expired
    level: int = -1  # level of the current dispatch (-1: none yet)
    current: str | None = None  # staff id holding it
    deadline: float = 0.0
    floor: int = 0  # lowest level still worth trying
    notified: set[str] = field(default_factory=set)
    snoozed: bool = False


class Escalator:
    def __init__(
        self,
        staff: list[Staff],
        schedule: ShiftSchedule,
        policy: EscalationPolicy | None = None,
        budget: AlertBudget | None = None,
    ) -> None:
        self.staff = {s.id: s for s in staff}
        self.schedule = schedule
        self.policy = policy or EscalationPolicy()
        self.budget = budget
        self.tracker = AckTracker()
        self._alerts: dict[str, _Alert] = {}
        self._snoozed_until: dict[str, float] = {}

    # --- eligibility -------------------------------------------------------------------
    def eligible(self, s: Staff, t: float) -> bool:
        return (
            self.schedule.on_shift(s.id, t)
            and not in_dnd(s, t)
            and self._snoozed_until.get(s.id, -1e18) <= t
            and (self.budget is None or self.budget.allow(s.id, t))
        )

    def _candidates(self, level: int, section: str, t: float, skip: set[str]) -> list[Staff]:
        role = LEVELS[level]
        out = [
            s for s in self.staff.values()
            if s.role == role and (role == "manager" or s.section == section)
            and s.id not in skip and self.eligible(s, t)
        ]  # fmt: skip
        return sorted(out, key=lambda s: s.id)

    def next_recipient(self, section: str, t: float) -> Staff | None:
        """Who a fresh alert for this section would reach right now (None: nobody available)."""
        for lvl in range(len(LEVELS)):
            c = self._candidates(lvl, section, t, set())
            if c:
                return c[0]
        return None

    # --- lifecycle ---------------------------------------------------------------------
    def start(
        self, alert_id: str, section: str, t: float, tables: tuple[str, ...] = ()
    ) -> list[Dispatch]:
        if alert_id in self._alerts:
            return []  # idempotent
        a = _Alert(alert_id, section, tuple(tables), t)
        self._alerts[alert_id] = a
        return self._dispatch(a, t)

    def _dispatch(self, a: _Alert, t: float) -> list[Dispatch]:
        for lvl in range(a.floor, len(LEVELS)):
            cands = self._candidates(lvl, a.section, t, a.notified)
            if not cands:
                continue
            s = cands[0]
            a.level, a.current, a.deadline = lvl, s.id, t + self.policy.ack_timeout_s[lvl]
            a.notified.add(s.id)
            a.snoozed = False
            if self.budget:
                self.budget.record(s.id, t)
            self.tracker.register(f"{a.id}:{s.id}", a.id, s.id, t)
            return [Dispatch(a.id, s.id, s.role, lvl, t, a.section, a.tables)]
        a.level, a.current = -1, None
        return []

    def tick(self, t: float) -> list[Dispatch]:
        out: list[Dispatch] = []
        for a in self._alerts.values():
            if a.status != "pending":
                continue
            if t - a.created >= self.policy.max_pending_s:
                self._expire(a, t)
                continue
            if a.current is None:  # waiting for someone to become reachable
                out += self._dispatch(a, t)
            elif t >= a.deadline:
                self.tracker.apply(f"{a.id}:{a.current}", DeliveryState.EXPIRED, t)
                a.floor = a.level + 1
                if a.floor >= len(LEVELS):
                    a.status = "expired"  # top of the chain timed out: stop, never loop
                    continue
                out += self._dispatch(a, t)
        return out

    def _expire(self, a: _Alert, t: float) -> None:
        a.status = "expired"
        if a.current:
            self.tracker.apply(f"{a.id}:{a.current}", DeliveryState.EXPIRED, t)

    def ack(self, alert_id: str, staff_id: str, t: float) -> bool:
        a = self._alerts.get(alert_id)
        if a is None or staff_id not in a.notified:
            return False
        if a.status == "acked":
            return True  # repeated ack
        if a.status != "pending":
            return False
        a.status = "acked"
        self.tracker.apply(f"{a.id}:{staff_id}", DeliveryState.ACKED, t)
        return True

    def resolve(self, alert_id: str, t: float) -> bool:
        """Table attended or vacated: close the alert; nobody gets a stale nudge afterwards."""
        a = self._alerts.get(alert_id)
        if a is None or a.status in ("resolved", "expired"):
            return False
        a.status = "resolved"
        for r in self.tracker.for_alert(alert_id):
            self.tracker.apply(r.delivery_id, DeliveryState.RESOLVED, t)
        return True

    def snooze(self, staff_id: str, t: float, duration_s: float) -> float:
        """Quiet this person for up to max_snooze_s; also defers (once) their pending deadlines."""
        d = min(max(duration_s, 0.0), self.policy.max_snooze_s)
        self._snoozed_until[staff_id] = max(self._snoozed_until.get(staff_id, 0.0), t + d)
        for a in self._alerts.values():
            if a.status == "pending" and a.current == staff_id and not a.snoozed:
                a.deadline += d
                a.snoozed = True
        return t + d

    def status(self, alert_id: str) -> str:
        return self._alerts[alert_id].status


class AlertRouter:
    """Live vs digest: live alerts go straight to the escalator; otherwise tables are held per
    section and sent as ONE digest when the section's spacing and the budget allow."""

    def __init__(self, esc: Escalator, min_gap_s: float = 90.0) -> None:
        self.esc = esc
        self.min_gap_s = min_gap_s
        self._held: dict[str, dict[str, float]] = {}
        self._last: dict[str, float] = {}
        self._live: dict[str, str] = {}  # table -> live alert id
        self._n = 0
        self.stats = {"live": 0, "digests": 0, "merged": 0, "dropped": 0}

    def _fire(self, section: str, tables: tuple[str, ...], t: float, prefix: str) -> list[Dispatch]:
        self._n += 1
        aid = f"{prefix}-{section}-{self._n}"
        d = self.esc.start(aid, section, t, tables)
        if d:
            self._last[section] = t
            for tb in tables:
                self._live[tb] = aid
        return d

    def submit(self, table: str, section: str, t: float, mode: str) -> list[Dispatch]:
        if mode == "off":
            return []
        free = t - self._last.get(section, -1e18) >= self.min_gap_s
        held = self._held.get(section)
        if mode == "live" and free and not held and self.esc.next_recipient(section, t):
            d = self._fire(section, (table,), t, "a")
            self.stats["live"] += bool(d)
            return d
        self._held.setdefault(section, {})[table] = t
        return []

    def flush(self, t: float) -> list[Dispatch]:
        out: list[Dispatch] = []
        for section, held in self._held.items():
            stale = [k for k, v in held.items() if t - v >= self.esc.policy.max_pending_s]
            for k in stale:
                del held[k]
                self.stats["dropped"] += 1
            free = t - self._last.get(section, -1e18) >= self.min_gap_s
            if held and free and self.esc.next_recipient(section, t):
                tables = tuple(sorted(held))
                d = self._fire(section, tables, t, "d")
                if d:
                    held.clear()
                    self.stats["digests"] += 1
                    self.stats["merged"] += len(tables)
                    out += d
        return out

    def table_resolved(self, table: str, t: float) -> None:
        for held in self._held.values():
            held.pop(table, None)
        aid = self._live.pop(table, None)
        if aid:
            self.esc.resolve(aid, t)
