"""Queue length and wait estimates for counter service and bars, with sanity checks and alerts.

All inputs are plain numbers/timestamps (seconds); the perception layer supplies counts with an
``uncertain`` flag. Nothing here claims more than the data supports: when throughput is unknown
or the queue is not moving the estimate is ``None`` with a reason, never a fabricated number.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from itertools import pairwise
from statistics import median


@dataclass(frozen=True)
class QueueSample:
    t: float
    length: int
    uncertain: bool = False      # camera stale / low confidence: sample is ignored


@dataclass(frozen=True)
class QueueVisit:
    """One guest's time in the queue (enter and leave are epoch seconds; leave None = still in)."""
    enter: float
    leave: float | None
    served: bool = True          # False = abandoned (balked/reneged)


def estimate_wait(queue_len: int, departures: list[float], now: float, *, window_s: float = 600.0,
                  min_departures: int = 3, max_plausible_s: float = 2 * 3600.0,
                  observed_waits: list[float] | None = None) -> dict:
    """Wait for someone joining now = queue length / recent departure rate (Little's law, W = L/lambda).

    Assumptions: FIFO, a single logical queue, and that the departure rate over the last
    ``window_s`` persists. ``departures`` are times guests left the queue served. Sanity checks:
    * negative length rejected;
    * empty queue -> wait 0;
    * fewer than ``min_departures`` in the window -> no estimate ("not enough throughput data");
    * queue > 0 and no departure for a whole window -> ``stalled`` (no estimate);
    * estimate above ``max_plausible_s`` is capped and flagged ``capped``;
    * if recent ``observed_waits`` (actual waits of guests who just left) exist and the estimate
      differs from their median by more than 2x either way, ``inconsistent`` is set so the UI can
      show a wider/softer number.
    The window is clipped to the observed span so early in the day the rate is not understated.
    """
    if queue_len < 0:
        raise ValueError("queue_len must be >= 0")
    if queue_len == 0:
        return {"ok": True, "wait_s": 0.0, "flags": []}
    recent = sorted(d for d in departures if now - window_s <= d <= now)
    if not recent:
        return {"ok": False, "stalled": True, "flags": ["stalled"],
                "reason": "queue is non-empty and nobody has been served recently"}
    if len(recent) < min_departures:
        return {"ok": False, "flags": [], "reason": "not enough throughput data"}
    span = max(min(window_s, now - recent[0]), 60.0)   # floor avoids huge rates from a burst
    rate = len(recent) / span
    wait = queue_len / rate
    flags = []
    if wait > max_plausible_s:
        wait, flags = max_plausible_s, ["capped"]
    if observed_waits:
        ref = median(observed_waits)
        if ref > 0 and not (0.5 <= wait / ref <= 2.0):
            flags.append("inconsistent")
    return {"ok": True, "wait_s": wait, "rate_per_min": rate * 60, "n_departures": len(recent),
            "flags": flags}


def littles_law_check(visits: list[QueueVisit], window: tuple[float, float], *,
                      tolerance: float = 0.25, min_visits: int = 10) -> dict:
    """Check L = lambda * W on logged visits, to decide whether the queue data is trustworthy.

    Over the window: L is the exact time-average number in queue (visit intervals clipped to the
    window); lambda is arrivals per second; W is the mean time in queue of visits that entered
    in the window (open visits are clipped at window end). Boundary effects mean the identity is
    only approximate for short windows or long waits, so the check is relative with a tolerance
    and refuses below ``min_visits``. A failed check means counts/timestamps disagree (double
    counting, missed departures): do not publish wait estimates from that data. Abandoned visits
    are included, since they occupied the queue.
    """
    lo, hi = window
    if hi <= lo:
        raise ValueError("window end must be after start")
    T = hi - lo
    arrivals = [v for v in visits if lo <= v.enter < hi]
    if len(arrivals) < min_visits:
        return {"ok": None, "reason": f"only {len(arrivals)} arrivals (need {min_visits})"}
    area = 0.0
    for v in visits:
        end = hi if v.leave is None else min(v.leave, hi)
        a, b = max(lo, v.enter), end
        if v.leave is not None and v.leave < v.enter:
            return {"ok": False, "reason": "visit leaves before it enters"}
        if b > a:
            area += b - a
    L = area / T
    lam = len(arrivals) / T
    W = sum(((hi if v.leave is None else min(v.leave, hi)) - v.enter) for v in arrivals) \
        / len(arrivals)
    rhs = lam * W
    rel = abs(L - rhs) / max(L, rhs, 1e-9)
    return {"ok": rel <= tolerance, "L": L, "lambda_per_s": lam, "W_s": W, "relative_gap": rel}


@dataclass(frozen=True)
class QueueAlertConfig:
    max_len: int = 8               # raise when length >= this ...
    clear_len: int = 5             # ... until length <= this (hysteresis)
    sustain_s: float = 60.0        # must hold this long before raising (ignore a brief clump)
    max_wait_s: float = 600.0
    stall_s: float = 240.0         # no departures this long with guests waiting
    cooldown_s: float = 300.0      # minimum gap between alerts of the same kind


@dataclass
class _Kind:
    since: float | None = None
    active: bool = False
    last: float = -1e18


def queue_alerts(samples: list[QueueSample], departures: list[float],
                 cfg: QueueAlertConfig | None = None) -> list[dict]:
    """Replay samples and return alerts: ``long_queue``, ``long_wait``, ``stalled``.

    Rules: uncertain samples are skipped entirely (no alert, no clearing: we do not know);
    samples are processed in time order, duplicates by timestamp keep the last; a condition must
    hold ``sustain_s`` before alerting and must drop below the clear threshold to re-arm; each
    kind has a cooldown. Wait uses ``estimate_wait`` and is silent when no estimate exists.
    ``long_wait`` clears at 80% of ``max_wait_s``. Assumes ``cfg.clear_len < cfg.max_len``.
    """
    cfg = cfg or QueueAlertConfig()
    if cfg.clear_len >= cfg.max_len:
        raise ValueError("clear_len must be below max_len (hysteresis)")
    by_t: dict[float, QueueSample] = {}
    for s in sorted(samples, key=lambda s: s.t):
        by_t[s.t] = s
    kinds = {"long_queue": _Kind(), "long_wait": _Kind(), "stalled": _Kind()}
    out: list[dict] = []
    deps = sorted(departures)

    def step(kind: str, t: float, cond: bool, clear: bool, **detail) -> None:
        k = kinds[kind]
        if k.active:
            if clear:
                k.active, k.since = False, None
            return
        if cond:
            k.since = t if k.since is None else k.since
            if t - k.since >= cfg.sustain_s and t - k.last >= cfg.cooldown_s:
                k.active, k.last = True, t
                out.append({"t": t, "kind": kind, **detail})
        else:
            k.since = None

    for t, s in by_t.items():
        if s.uncertain or s.length < 0:
            continue
        step("long_queue", t, s.length >= cfg.max_len, s.length <= cfg.clear_len, length=s.length)
        w = estimate_wait(s.length, [d for d in deps if d <= t], t)
        if w.get("ok"):
            step("long_wait", t, w["wait_s"] >= cfg.max_wait_s,
                 w["wait_s"] <= 0.8 * cfg.max_wait_s, wait_s=w["wait_s"])
        last_dep = max((d for d in deps if d <= t), default=None)
        idle = t - last_dep if last_dep is not None else None
        stalled = s.length > 0 and idle is not None and idle >= cfg.stall_s
        step("stalled", t, stalled, s.length == 0 or (idle is not None and idle < cfg.stall_s),
             idle_s=idle)
    return out


@dataclass
class QueueSummary:
    samples: int = 0
    skipped_uncertain: int = 0
    max_len: int = 0
    time_avg_len: float | None = None
    notes: list[str] = field(default_factory=list)


def summarize_queue(samples: list[QueueSample]) -> QueueSummary:
    """Time-weighted average and max queue length (step interpolation between samples).

    Uncertain samples are dropped (counted). A gap longer than 10x the median sample spacing
    is not interpolated across (treated as missing) and noted.
    """
    good = sorted((s for s in samples if not s.uncertain and s.length >= 0), key=lambda s: s.t)
    out = QueueSummary(len(samples), len(samples) - len(good))
    if not good:
        return out
    out.max_len = max(s.length for s in good)
    if len(good) < 2:
        out.notes.append("single sample: no time average")
        return out
    gaps = [b.t - a.t for a, b in pairwise(good) if b.t > a.t]
    if not gaps:
        return out
    lim = 10 * median(gaps)
    area = span = 0.0
    for a, b in pairwise(good):
        d = b.t - a.t
        if d <= 0:
            continue
        if d > lim:
            out.notes.append(f"gap of {d:.0f}s not interpolated")
            continue
        area += a.length * d
        span += d
    out.time_avg_len = area / span if span else None
    return out
