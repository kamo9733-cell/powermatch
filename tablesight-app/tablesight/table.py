"""Table state machine. Consumes per-tick observations, emits events. No video dependency.

States: EMPTY -> SEATED (confirmed) -> ... -> EMPTY (confirmed) -> NEEDS_CLEAN (optional).
Hysteresis + absence grace keep restroom trips, walk-bys and flicker from creating false visits.
"""
from dataclasses import dataclass, field
from enum import Enum

from .templates import VenueTemplate


class State(str, Enum):
    EMPTY = "empty"
    SEATED = "seated"
    NEEDS_CLEAN = "needs_clean"


@dataclass(frozen=True)
class Observation:
    t: float                 # seconds (UTC epoch or sim time)
    guests: int              # guests in table zone
    staff: int               # staff in table zone
    confidence: float = 1.0  # perception confidence 0..1; low => treated as uncertain
    stale: bool = False      # camera frozen/offline: never infer anything


@dataclass(frozen=True)
class Event:
    t: float
    table: str
    kind: str    # seated | vacated | staff_visit | needs_attention | needs_clean | uncertain
    detail: dict = field(default_factory=dict)


MIN_CONFIDENCE = 0.5


@dataclass
class Table:
    table_id: str
    tpl: VenueTemplate
    state: State = State.EMPTY
    party_size: int = 0
    seated_at: float | None = None
    last_staff_t: float | None = None
    vacated_at: float | None = None
    _pending_since: float | None = None   # start of a continuous contrary reading
    _absent_since: float | None = None
    _staff_since: float | None = None
    _flagged: bool = False
    _blind: bool = False                 # camera stale / low confidence: we know nothing
    _blind_start: float | None = None
    _last_fresh_t: float | None = None
    _cand_party: int = 0
    _cand_n: int = 0
    events: list[Event] = field(default_factory=list)

    def _emit(self, t: float, kind: str, **detail) -> None:
        self.events.append(Event(t, self.table_id, kind, detail))

    def step(self, o: Observation) -> None:
        if o.stale or o.confidence < MIN_CONFIDENCE:
            # Honesty rule: no guesses. Pause all timers' inputs and say so.
            self._pending_since = self._absent_since = self._staff_since = None
            if not self._blind:
                self._blind = True
                self._blind_start = self._last_fresh_t if self._last_fresh_t is not None else o.t
                self._emit(o.t, "uncertain", stale=o.stale, confidence=o.confidence)
            return
        if self._blind:
            self._recover(o.t)
        self._last_fresh_t = o.t
        self._track_staff(o)
        if self.state is State.SEATED:
            self._step_seated(o)
        else:
            self._step_unseated(o)

    def _recover(self, t: float) -> None:
        """Time we were blind must not count as neglect or as a staff visit: shift the clocks forward."""
        gap = t - (self._blind_start if self._blind_start is not None else t)
        self._blind, self._blind_start = False, None
        for name in ("seated_at", "last_staff_t", "vacated_at"):
            v = getattr(self, name)
            if v is not None:
                setattr(self, name, v + gap)
        self._emit(t, "uncertain_end", blind_s=gap)

    def _track_staff(self, o: Observation) -> None:
        if o.staff > 0:
            if self._staff_since is None:
                self._staff_since = o.t
            if o.t - self._staff_since >= self.tpl.min_visit_s and self.state is State.SEATED:
                if self.last_staff_t is None or o.t - self.last_staff_t > self.tpl.min_visit_s:
                    self._emit(o.t, "staff_visit")
                self.last_staff_t = o.t
                self._flagged = False
        else:
            self._staff_since = None

    def _step_unseated(self, o: Observation) -> None:
        if o.guests > 0:
            self._pending_since = self._pending_since if self._pending_since is not None else o.t
            if o.t - self._pending_since >= self.tpl.seat_confirm_s:
                self.state, self.seated_at = State.SEATED, self._pending_since
                self.party_size, self.last_staff_t = o.guests, None
                self._pending_since = self._absent_since = None
                self._flagged = False
                self._emit(o.t, "seated", party=o.guests)
        else:
            self._pending_since = None
            self._check_dirty(o)

    def _check_dirty(self, o: Observation) -> None:
        d = self.tpl.dirty_alert_s
        if self.vacated_at is None or d is None or self.state is State.NEEDS_CLEAN:
            return
        if o.t - self.vacated_at >= d:
            self.state = State.NEEDS_CLEAN
            self._emit(o.t, "needs_clean", waited=o.t - self.vacated_at)

    def _step_seated(self, o: Observation) -> None:
        if o.guests > 0:
            self._absent_since = None
            if o.guests > self.party_size and o.guests == self._cand_party:
                self._cand_n += 1
                if self._cand_n >= 5:
                    self.party_size = o.guests
            else:
                self._cand_party, self._cand_n = o.guests, 1
            self._check_neglect(o)
            return
        self._absent_since = self._absent_since if self._absent_since is not None else o.t
        gone = o.t - self._absent_since
        if gone >= self.tpl.absence_grace_s and gone >= self.tpl.leave_confirm_s:
            self.state, self.vacated_at = State.EMPTY, self._absent_since
            self._emit(o.t, "vacated", dwell=self._absent_since - (self.seated_at or 0),
                       party=self.party_size)
            self.party_size, self._absent_since, self._pending_since = 0, None, None

    def _check_neglect(self, o: Observation) -> None:
        if not self.tpl.table_service or self._flagged:
            return
        ref = self.last_staff_t if self.last_staff_t is not None else self.seated_at
        limit = self.tpl.attended_window_s if self.last_staff_t is not None else self.tpl.greet_alert_s
        if ref is not None and limit > 0 and o.t - ref >= limit:
            self._flagged = True
            self._emit(o.t, "needs_attention", waited=o.t - ref,
                       first_visit=self.last_staff_t is None, party=self.party_size)
