"""Shift reports, like-with-like day comparison, and revenue per seat-hour (POS interface).

Principles (CLAUDE.md 4.6): medians/percentiles never bare averages, small-sample flags on every
metric, team-level framing that blames no individual, comparisons only between comparable days
(same weekday, same daypart), and honest refusal when there is not enough data.

Time model: event times are UTC epoch seconds. Durations are real elapsed seconds, so DST
transitions never distort them. Calendar logic (business day, weekday, daypart) is done on local
wall-clock time through ``zoneinfo`` and reuses ``analytics.business_day`` semantics: a venue open
past midnight attributes 01:00 Saturday to Friday's business day.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from statistics import median
from zoneinfo import ZoneInfo

from .analytics import business_day, percentile
from .table import Event

MIN_N = 5            # below this, a median is shown but flagged unreliable
MIN_N_P90 = 10       # a 90th percentile from fewer samples is mostly the max; flagged unreliable
MAX_PLAUSIBLE_DWELL_S = 6 * 3600.0

# Dayparts on the "business clock": local hour, +24 after midnight but before rollover.
DAYPARTS: dict[str, tuple[float, float]] = {
    "breakfast": (5, 11), "lunch": (11, 15), "afternoon": (15, 17),
    "dinner": (17, 22), "late": (22, 29),
}
STAFF_CAVEAT = ("Staff-level numbers are small, depend on which tables and times a person was "
                "given, and are not a performance rating. Use for coaching conversations only.")


# ---------------------------------------------------------------------------------------------
# Calendar helpers
# ---------------------------------------------------------------------------------------------
def local_parts(t: float, tz: str = "UTC") -> tuple[int, float]:
    """(local date ordinal, local wall-clock hour as float) for epoch seconds ``t``."""
    dt = datetime.fromtimestamp(t, tz=ZoneInfo(tz))
    return dt.toordinal(), dt.hour + dt.minute / 60 + dt.second / 3600


def business_day_of(t: float, tz: str = "UTC", rollover_hour: float = 5.0) -> int:
    """Business-day ordinal of an instant. Uses analytics.business_day semantics.

    Assumption: wall-clock hour decides, so on a DST fall-back night the repeated 01:xx hour
    still maps to the previous business day (both occurrences are before rollover).
    """
    ordinal, hour = local_parts(t, tz)
    return business_day(hour, ordinal, rollover_hour)


def daypart_of(t: float, tz: str = "UTC", rollover_hour: float = 5.0) -> str:
    """Daypart name of an instant on the business clock (after-midnight hours count as 24+)."""
    _, hour = local_parts(t, tz)
    if hour < rollover_hour:
        hour += 24
    for name, (lo, hi) in DAYPARTS.items():
        if lo <= hour < hi:
            return name
    return "late"


def split_business_days(events: list[Event], tz: str = "UTC",
                        rollover_hour: float = 5.0) -> dict[int, list[Event]]:
    """Group events by business-day ordinal, each group sorted by time."""
    out: dict[int, list[Event]] = {}
    for e in sorted(events, key=lambda e: e.t):
        out.setdefault(business_day_of(e.t, tz, rollover_hour), []).append(e)
    return out


# ---------------------------------------------------------------------------------------------
# Metric summaries
# ---------------------------------------------------------------------------------------------
def summarize(xs: list[float], min_n: int = MIN_N, min_n_p90: int = MIN_N_P90) -> dict:
    """Robust summary with small-sample flags. n == 0 returns None statistics.

    ``reliable`` refers to the median; ``p90_reliable`` is stricter. The min/max are included so
    a reader can see a range rather than a single number.
    """
    if not xs:
        return {"n": 0, "median_s": None, "p90_s": None, "min_s": None, "max_s": None,
                "reliable": False, "p90_reliable": False}
    return {"n": len(xs), "median_s": median(xs), "p90_s": percentile(xs, 0.9),
            "min_s": min(xs), "max_s": max(xs),
            "reliable": len(xs) >= min_n, "p90_reliable": len(xs) >= min_n_p90}


@dataclass
class Visit:
    table: str
    seated_t: float
    party: int
    staff_times: list[float]
    staff_ids: list[str | None]
    dwell_s: float | None = None     # None while still seated / never closed


def build_visits(events: list[Event]) -> list[Visit]:
    """Reconstruct table visits from seated / staff_visit / vacated events.

    Assumptions: events per table are ordered by time; a ``seated`` while a visit is still open
    means the ``vacated`` was missed, so the stale visit is kept without a dwell (never invented).
    A ``vacated`` without an open visit is ignored. Dwell is taken from ``detail['dwell']`` (the
    state machine's value, which excludes the leave grace period) else from timestamps.
    """
    open_: dict[str, Visit] = {}
    done: list[Visit] = []
    for e in sorted(events, key=lambda e: e.t):
        if e.kind == "seated":
            if e.table in open_:
                done.append(open_.pop(e.table))
            open_[e.table] = Visit(e.table, e.t, int(e.detail.get("party", 0) or 0), [], [])
        elif e.kind == "staff_visit" and e.table in open_:
            open_[e.table].staff_times.append(e.t)
            open_[e.table].staff_ids.append(e.detail.get("staff"))
        elif e.kind == "vacated" and e.table in open_:
            v = open_.pop(e.table)
            v.dwell_s = float(e.detail["dwell"]) if "dwell" in e.detail else e.t - v.seated_t
            done.append(v)
    done.extend(open_.values())
    return sorted(done, key=lambda v: v.seated_t)


def _alert_report(events: list[Event], alerts: list[dict] | None, acks: list[dict] | None,
                  min_n: int) -> dict:
    """Alerts raised, sent and acknowledged.

    ``needs_attention`` events are conditions detected; ``alerts`` (AlertEngine.sent dicts with
    keys t, tables) are what actually reached phones; ``acks`` are dicts {t, table}. An alert is
    acknowledged if any of its tables has an ack at or after the alert time and before the next
    alert covering that table (so one ack is not credited to several alerts).
    """
    detected = sum(1 for e in events if e.kind == "needs_attention")
    sent = sorted(alerts or [], key=lambda a: a["t"])
    pending = sorted(acks or [], key=lambda a: a["t"])
    used: set[int] = set()
    acked = 0
    for a in sent:
        hit = None
        for i, k in enumerate(pending):
            if i not in used and k["t"] >= a["t"] and k["table"] in a["tables"]:
                hit = i
                break
        if hit is not None:
            used.add(hit)
            acked += 1
    return {"detected": detected, "sent": len(sent), "acknowledged": acked,
            "ack_rate": (acked / len(sent)) if sent else None,
            "reliable": len(sent) >= min_n,
            "note": "Unacknowledged alerts may mean alert fatigue or a rush, not neglect."}


def _systemic_assessment(visits: list[Visit], slow_greet_s: float, min_n: int) -> dict:
    """Is slow greeting load-related (systemic) or undetermined? Never points at a person.

    Heuristic: concurrency = number of visits open at each seating. If greets in the busier half
    are at least 1.5x slower than in the quieter half (both halves >= min_n // 2 + 1 samples) the
    pattern is labelled load-related. Slow greets spread over many tables point the same way.
    Otherwise the report says it cannot tell. It deliberately has no 'individual' verdict.
    """
    rows = []
    for v in visits:
        if not v.staff_times:
            continue
        conc = sum(1 for w in visits if w.seated_t <= v.seated_t
                   and (w.dwell_s is None or w.seated_t + w.dwell_s >= v.seated_t))
        rows.append((conc, v.staff_times[0] - v.seated_t, v.table))
    rows = [r for r in rows if r[1] >= 0]
    if len(rows) < min_n:
        return {"attribution": "insufficient data", "n": len(rows),
                "finding": "Too few greeted visits to say anything about causes."}
    conc_med = median(r[0] for r in rows)
    busy = [r[1] for r in rows if r[0] > conc_med]
    quiet = [r[1] for r in rows if r[0] <= conc_med]
    slow_tables = {r[2] for r in rows if r[1] >= slow_greet_s}
    all_tables = {r[2] for r in rows}
    need = min_n // 2 + 1
    out = {"n": len(rows), "slow_tables": len(slow_tables), "tables": len(all_tables),
           "busy_median_s": median(busy) if busy else None,
           "quiet_median_s": median(quiet) if quiet else None}
    if len(busy) >= need and len(quiet) >= need and median(busy) >= 1.5 * max(median(quiet), 1.0):
        out["attribution"] = "systemic: load-related"
        out["finding"] = ("Greets slow down when the floor is busy; that points at coverage and "
                          "staffing for those periods, not at individuals.")
    elif len(slow_tables) >= max(3, len(all_tables) // 2):
        out["attribution"] = "systemic: widespread"
        out["finding"] = ("Slow greets are spread across many tables; look at process and "
                          "coverage before anything else.")
    else:
        out["attribution"] = "undetermined"
        out["finding"] = "No clear pattern; do not infer causes from this shift alone."
    return out


def shift_report(events: list[Event], *, alerts: list[dict] | None = None,
                 acks: list[dict] | None = None, window: tuple[float, float] | None = None,
                 min_n: int = MIN_N, slow_greet_s: float = 300.0,
                 greet_buckets_s: tuple[float, ...] = (120, 300, 600),
                 max_dwell_s: float = MAX_PLAUSIBLE_DWELL_S,
                 allow_staff_level: bool = False) -> dict:
    """Team-level shift report from events. Pure function; empty input returns a valid report.

    Event conventions: ``seated``(party), ``staff_visit`` (optional detail['staff']),
    ``vacated``(dwell, party), ``needs_attention``, ``walk_away`` (optional detail['waited']
    seconds; emitted by a host/queue module, not by the table state machine).

    Metrics: turn (dwell) median/p90, greet time distribution (seat to first staff visit, measured
    from the ``seated`` event, which is stamped after seat confirmation, so it understates real
    greet time by that lag), check-back gaps (between consecutive staff visits within a visit),
    walk-aways, alerts detected/sent/acknowledged. Dwells <= 0 or above ``max_dwell_s`` are
    excluded as sensor artefacts and counted in ``excluded``. Every summary carries ``n`` and
    ``reliable``. Staff-level breakdown is off unless ``allow_staff_level`` is set, is suppressed
    for any person under ``min_n`` greets, is alphabetical (never ranked) and carries a caveat.
    """
    if window is not None:
        lo, hi = window
        if hi <= lo:
            raise ValueError("window end must be after start")
        events = [e for e in events if lo <= e.t < hi]
    visits = build_visits(events)
    dwells_all = [v.dwell_s for v in visits if v.dwell_s is not None]
    dwells = [d for d in dwells_all if 0 < d <= max_dwell_s]
    greets = [v.staff_times[0] - v.seated_t for v in visits if v.staff_times]
    greets = [g for g in greets if g >= 0]
    gaps = [b - a for v in visits for a, b in zip(v.staff_times, v.staff_times[1:], strict=False)]
    gaps = [g for g in gaps if g > 0]
    never_greeted = sum(1 for v in visits if not v.staff_times and v.dwell_s is not None)

    edges = sorted(greet_buckets_s)
    labels = [f"<{int(edges[0])}s"] + [f"{int(a)}-{int(b)}s" for a, b in
                                        zip(edges, edges[1:], strict=False)] + [f">={int(edges[-1])}s"]
    counts = [0] * len(labels)
    for g in greets:
        counts[sum(1 for x in edges if g >= x)] += 1

    walk = [e for e in events if e.kind == "walk_away"]
    waited = [float(e.detail["waited"]) for e in walk if "waited" in e.detail]
    greet_summary = summarize(greets, min_n)
    greet_summary["distribution"] = dict(zip(labels, counts, strict=True))
    greet_summary["never_greeted_before_leaving"] = never_greeted

    report = {
        "visits": len(visits),
        "turn": summarize(dwells, min_n),
        "greet": greet_summary,
        "checkback_gap": summarize(gaps, min_n),
        "walk_aways": {"n": len(walk), "wait_before_leaving": summarize(waited, min_n)},
        "alerts": _alert_report(events, alerts, acks, min_n),
        "excluded": {"dwell_implausible": len(dwells_all) - len(dwells)},
        "framing": _systemic_assessment(visits, slow_greet_s, min_n),
        "scope": "team",
    }
    if window is not None:
        report["hours"] = (window[1] - window[0]) / 3600.0   # real elapsed, DST-safe
    if allow_staff_level:
        report["staff"] = _staff_level(visits, min_n)
        report["scope"] = "team+staff"
        report["staff_caveat"] = STAFF_CAVEAT
    return report


def _staff_level(visits: list[Visit], min_n: int) -> dict[str, dict]:
    per: dict[str, list[float]] = {}
    for v in visits:
        if v.staff_times and v.staff_ids[0] is not None and v.staff_times[0] >= v.seated_t:
            per.setdefault(str(v.staff_ids[0]), []).append(v.staff_times[0] - v.seated_t)
    out = {}
    for sid in sorted(per):
        xs = per[sid]
        if len(xs) < min_n:
            out[sid] = {"n": len(xs), "suppressed": True,
                        "reason": f"fewer than {min_n} greets; not reported"}
        else:
            out[sid] = {"n": len(xs), "median_s": median(xs), "suppressed": False,
                        "caveat": STAFF_CAVEAT}
    return out


# ---------------------------------------------------------------------------------------------
# Like-with-like comparison
# ---------------------------------------------------------------------------------------------
def compare_like_with_like(events: list[Event], target_day: int, *, tz: str = "UTC",
                           daypart: str | None = None, weeks: int = 8, min_days: int = 3,
                           min_n_per_day: int = MIN_N, exclude_days: frozenset[int] = frozenset(),
                           rollover_hour: float = 5.0) -> dict:
    """Compare one business day with prior days of the same weekday (and daypart, if given).

    Only strictly earlier days with the same weekday, not in ``exclude_days`` (holidays, private
    events), within the last ``weeks`` weeks and with at least ``min_n_per_day`` turns in the
    slice are used. Fewer than ``min_days`` such days -> refuses (``comparable`` False). The
    reference is the median of daily median dwells with the min-max range so the reader sees
    natural day-to-day spread; a target inside that range is reported as 'within normal range'
    rather than as better or worse.
    """
    if daypart is not None and daypart not in DAYPARTS:
        raise ValueError(f"unknown daypart {daypart!r}")
    days = split_business_days(events, tz, rollover_hour)
    weekday = date.fromordinal(target_day).weekday()

    def day_turn(d: int) -> list[float]:
        evs = days.get(d, [])
        if daypart is not None:
            evs = [e for e in evs if daypart_of(e.t, tz, rollover_hour) == daypart]
        dw = [float(e.detail["dwell"]) for e in evs if e.kind == "vacated" and "dwell" in e.detail]
        return [x for x in dw if 0 < x <= MAX_PLAUSIBLE_DWELL_S]

    target = day_turn(target_day)
    ref_days, skipped = [], 0
    for d in sorted(days, reverse=True):
        if d >= target_day or target_day - d > weeks * 7 or d in exclude_days:
            continue
        if date.fromordinal(d).weekday() != weekday:
            continue
        xs = day_turn(d)
        if len(xs) < min_n_per_day:
            skipped += 1
            continue
        ref_days.append(median(xs))
    out = {"weekday": weekday, "daypart": daypart, "target_n": len(target),
           "reference_days": len(ref_days), "skipped_thin_days": skipped}
    if len(ref_days) < min_days:
        return {**out, "comparable": False,
                "reason": f"only {len(ref_days)} comparable days (need {min_days})"}
    if not target:
        return {**out, "comparable": False, "reason": "no turns on target day/daypart"}
    ref, lo, hi = median(ref_days), min(ref_days), max(ref_days)
    t_med = median(target)
    verdict = ("within normal range" if lo <= t_med <= hi
               else "slower than usual" if t_med > hi else "faster than usual")
    return {**out, "comparable": True, "target_median_s": t_med,
            "target_reliable": len(target) >= min_n_per_day,
            "reference_median_s": ref, "reference_range_s": (lo, hi), "verdict": verdict,
            "note": "Compared with the same weekday/daypart only; check for events or weather "
                    "before drawing conclusions."}


# ---------------------------------------------------------------------------------------------
# Revenue per available seat-hour (RevPASH) with a POS-event interface
# ---------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class PosEvent:
    """Minimal POS interface. A future integration only has to emit these.

    kind: 'payment' (amount > 0 closes revenue), 'refund' (amount stored positive, subtracted).
    check_id de-duplicates retransmissions (POS webhooks resend).
    """
    t: float
    check_id: str
    amount: float
    kind: str = "payment"
    table: str | None = None


def net_revenue(pos: list[PosEvent], window: tuple[float, float]) -> dict:
    """Net revenue in [start, end). Duplicate (check_id, kind) pairs count once; unknown kinds,
    negative or non-finite amounts are rejected into ``rejected`` rather than silently summed."""
    lo, hi = window
    seen: set[tuple[str, str]] = set()
    total, n_dupe, rejected = 0.0, 0, 0
    for p in sorted(pos, key=lambda p: p.t):
        if not (lo <= p.t < hi):
            continue
        if p.kind not in ("payment", "refund") or not (p.amount == p.amount) or p.amount < 0 \
                or p.amount == float("inf"):
            rejected += 1
            continue
        key = (p.check_id, p.kind)
        if key in seen:
            n_dupe += 1
            continue
        seen.add(key)
        total += p.amount if p.kind == "payment" else -p.amount
    return {"revenue": total, "duplicates_ignored": n_dupe, "rejected": rejected}


def rev_per_seat_hour(pos: list[PosEvent], seats: int, window: tuple[float, float], *,
                      closed_seat_hours: float = 0.0, min_hours: float = 0.5) -> dict:
    """Revenue per available seat-hour = net revenue / (seats x elapsed hours - closed seat-hours).

    Elapsed hours are real (epoch difference), so a 25-hour fall-back day and a 23-hour spring day
    are measured correctly. Refuses (value None) when the available seat-hours are below
    ``min_hours`` (a nearly empty denominator explodes the ratio). Revenue is attributed by
    payment time, not seating time; in a short window a late check can land in the next window,
    so use windows of at least a daypart. Raises on seats <= 0 or an empty window.
    """
    lo, hi = window
    if seats <= 0:
        raise ValueError("seats must be positive")
    if hi <= lo:
        raise ValueError("window end must be after start")
    avail = seats * (hi - lo) / 3600.0 - closed_seat_hours
    nr = net_revenue(pos, window)
    out = {**nr, "available_seat_hours": avail}
    if avail < min_hours:
        return {**out, "revpash": None, "reason": "available seat-hours too small"}
    return {**out, "revpash": nr["revenue"] / avail}


def occupied_seat_hours(events: list[Event], window: tuple[float, float]) -> dict:
    """Sum of party size x duration of visits clipped to the window (guest-hours seated).

    Visits still open at window end are counted up to the end (flagged as ``open_visits``);
    visits with unknown party size contribute nothing and are counted in ``unknown_party``.
    Utilisation = occupied / available seats is a lower bound when parties sit at larger tables.
    """
    lo, hi = window
    if hi <= lo:
        raise ValueError("window end must be after start")
    total, open_n, unknown = 0.0, 0, 0
    for v in build_visits(events):
        end = v.seated_t + v.dwell_s if v.dwell_s is not None else hi
        if v.dwell_s is None:
            open_n += 1
        a, b = max(lo, v.seated_t), min(hi, end)
        if b <= a:
            continue
        if v.party <= 0:
            unknown += 1
            continue
        total += v.party * (b - a) / 3600.0
    return {"guest_hours": total, "open_visits": open_n, "unknown_party": unknown}
