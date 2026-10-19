"""Analytics over events. Uses medians/percentiles, never bare averages; flags small samples."""
from collections import defaultdict
from statistics import median

from .table import Event


def percentile(xs: list[float], q: float) -> float:
    s = sorted(xs)
    if not s:
        raise ValueError("empty")
    k = (len(s) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def turn_stats(events: list[Event], min_n: int = 5) -> dict:
    dw = [e.detail["dwell"] for e in events if e.kind == "vacated"]
    if not dw:
        return {"n": 0, "reliable": False}
    return {"n": len(dw), "median_s": median(dw), "p90_s": percentile(dw, 0.9),
            "reliable": len(dw) >= min_n}


def greet_times(events: list[Event]) -> list[float]:
    """Seconds from seated to first staff_visit, per table visit."""
    seated: dict[str, float] = {}
    out = []
    for e in sorted(events, key=lambda e: e.t):
        if e.kind == "seated":
            seated[e.table] = e.t
        elif e.kind == "staff_visit" and e.table in seated:
            out.append(e.t - seated.pop(e.table))
        elif e.kind == "vacated":
            seated.pop(e.table, None)
    return out


def forecast_covers(history: dict[int, list[int]], hour: int, weeks: int = 4) -> dict:
    """Seasonal-naive: median of the same hour on prior comparable days.
    history: hour -> covers on each prior comparable day. Returns range, not a point guess."""
    xs = history.get(hour, [])[-weeks:]
    if len(xs) < 3:
        return {"hour": hour, "covers": None, "reason": "insufficient comparable days"}
    return {"hour": hour, "covers": median(xs), "low": min(xs), "high": max(xs)}


def heatmap(points: list[tuple[float, float]], cell_m: float = 0.5) -> dict[tuple[int, int], int]:
    h: dict[tuple[int, int], int] = defaultdict(int)
    for x, y in points:
        h[(int(x // cell_m), int(y // cell_m))] += 1
    return dict(h)


def business_day(ts_local_hour: float, date_ordinal: int, rollover_hour: float = 5.0) -> int:
    """Venues open past midnight: 1am Saturday belongs to Friday's business day."""
    return date_ordinal - 1 if ts_local_hour < rollover_hour else date_ordinal
