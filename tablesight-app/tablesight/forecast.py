"""Cover forecasts (seasonal-naive and EW-ratio), honest backtests, and host table-ready estimates.

History format: ``dict[(business_day_ordinal, hour), covers]`` where the ordinal comes from
``reports.business_day_of`` (so after-midnight covers belong to the previous business day) and
``hour`` is the business-clock hour (0..29). The weekday is derived from the ordinal.

Every forecast returns a ``Forecast`` with a prediction interval, or refuses (``ok`` False with a
reason) when history is insufficient. Intervals are approximate: with a handful of comparable
days they are rough and are reported with the sample size so readers can judge them.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass
from datetime import date
from statistics import median

from .analytics import percentile

History = dict[tuple[int, int], float]
Z = {0.5: 0.674, 0.8: 1.2816, 0.9: 1.6449, 0.95: 1.96}


@dataclass(frozen=True)
class Forecast:
    ok: bool
    method: str
    day: int
    hour: int
    point: float | None = None
    low: float | None = None
    high: float | None = None
    level: float = 0.8
    n: int = 0
    reason: str = ""


def _z(level: float) -> float:
    if level not in Z:
        raise ValueError(f"level must be one of {sorted(Z)}")
    return Z[level]


def _weekday(day: int) -> int:
    return date.fromordinal(day).weekday()


def _comparable(history: History, day: int, hour: int, weeks: int,
                exclude: frozenset[int]) -> list[float]:
    """Same weekday + hour, strictly before ``day``, within ``weeks`` weeks, oldest first."""
    wd = _weekday(day)
    ds = sorted(d for (d, h) in history
                if h == hour and d < day and day - d <= weeks * 7 and d not in exclude
                and _weekday(d) == wd)
    out = []
    for d in ds:
        v = history[(d, hour)]
        if v is not None and math.isfinite(v) and v >= 0:     # drop NaN / negative sensor garbage
            out.append(float(v))
    return out


def _mad_sigma(xs: list[float]) -> float:
    m = median(xs)
    return 1.4826 * median(abs(x - m) for x in xs)


def seasonal_naive(history: History, day: int, hour: int, *, weeks: int = 8, min_n: int = 3,
                   level: float = 0.8, exclude: frozenset[int] = frozenset()) -> Forecast:
    """Median of the same weekday/hour on prior weeks; interval = median +/- z * sigma * sqrt(1+1/n).

    sigma is the MAD-based robust spread, floored by Poisson noise sqrt(median) so identical
    history never yields a zero-width interval (covers are counts). Outliers (a storm day) barely
    move the median. Assumes the weekly pattern is stable; it cannot anticipate holidays, trends
    or one-off events. Refuses with fewer than ``min_n`` comparable days.
    """
    xs = _comparable(history, day, hour, weeks, exclude)
    if len(xs) < min_n:
        return Forecast(False, "seasonal_naive", day, hour, n=len(xs), level=level,
                        reason=f"only {len(xs)} comparable days (need {min_n})")
    m = median(xs)
    sigma = max(_mad_sigma(xs), math.sqrt(max(m, 0.0)))
    half = _z(level) * sigma * math.sqrt(1 + 1 / len(xs))
    return Forecast(True, "seasonal_naive", day, hour, m, max(0.0, m - half), m + half,
                    level, len(xs))


def _day_ratios(history: History, days: list[int], weeks: int, min_n: int,
                exclude: frozenset[int]) -> list[float]:
    """Per-day ratio actual/seasonal-baseline using only data before each day (no leakage)."""
    out = []
    for d in days:
        num = den = 0.0
        for (dd, h), v in history.items():
            if dd != d:
                continue
            f = seasonal_naive(history, d, h, weeks=weeks, min_n=min_n, exclude=exclude)
            if f.ok and f.point and f.point > 0:
                num += v
                den += f.point
        if den > 0:
            out.append(num / den)
    return out


def ewma_ratio(history: History, day: int, hour: int, *, weeks: int = 8, min_n: int = 3,
               alpha: float = 0.4, recent_days: int = 14, level: float = 0.8,
               exclude: frozenset[int] = frozenset()) -> Forecast:
    """Seasonal baseline x exponentially weighted recent level ratio.

    The ratio is how the last ``recent_days`` days ran versus their own seasonal baseline,
    smoothed with weight ``alpha`` on the newest day. It lets the forecast follow a trend or a
    slow level shift. The interval combines the baseline interval (scaled by the ratio) with the
    ratio's robust spread in quadrature. Refuses if the baseline refuses or fewer than 3 recent
    days have a ratio. Assumes the ratio persists to ``day`` (one-step-ahead); do not use it to
    forecast weeks out. Days in ``exclude`` are neither used as baseline nor as ratio days.
    """
    if not 0 < alpha <= 1:
        raise ValueError("alpha must be in (0, 1]")
    base = seasonal_naive(history, day, hour, weeks=weeks, min_n=min_n, level=level,
                          exclude=exclude)
    if not base.ok:
        return Forecast(False, "ewma_ratio", day, hour, n=base.n, level=level, reason=base.reason)
    days = sorted({d for (d, _) in history if d < day and day - d <= recent_days
                   and d not in exclude})
    ratios = _day_ratios(history, days, weeks, min_n, exclude)
    if len(ratios) < 3:
        return Forecast(False, "ewma_ratio", day, hour, n=len(ratios), level=level,
                        reason=f"only {len(ratios)} recent days with a usable ratio (need 3)")
    r = ratios[0]
    for x in ratios[1:]:
        r = alpha * x + (1 - alpha) * r
    # Clamp: a ratio far from 1 almost certainly reflects broken data, not demand.
    r = min(max(r, 0.5), 2.0)
    s_r = max(_mad_sigma(ratios), 0.03)
    point = base.point * r
    z = _z(level)
    lo_b, hi_b = (base.point - base.low) * r, (base.high - base.point) * r
    ratio_half = z * s_r * base.point * math.sqrt(alpha / (2 - alpha) + 1 / len(ratios))
    low = max(0.0, point - math.hypot(lo_b, ratio_half))
    high = point + math.hypot(hi_b, ratio_half)
    return Forecast(True, "ewma_ratio", day, hour, point, low, high, level, base.n)


METHODS = {"seasonal_naive": seasonal_naive, "ewma_ratio": ewma_ratio}


def backtest(history: History, test_days: list[int], method: str = "seasonal_naive",
             level: float = 0.8, **kw) -> dict:
    """Rolling-origin backtest: each (day, hour) is forecast from data strictly before ``day``.

    Reports MAE, WAPE (sum |err| / sum actual; undefined if actuals sum to 0), bias, empirical
    interval coverage against the nominal ``level``, and how many points were refused.
    Does not tune anything on the test days. Coverage on few points is noisy; ``n`` is returned.
    """
    fn = METHODS[method]
    errs, covered, refused, actual_sum, signed = [], 0, 0, 0.0, 0.0
    for d in test_days:
        for (dd, h), v in sorted(history.items()):
            if dd != d:
                continue
            f = fn(history, d, h, level=level, **kw)
            if not f.ok:
                refused += 1
                continue
            e = f.point - v
            errs.append(abs(e))
            signed += e
            actual_sum += v
            covered += f.low <= v <= f.high
    n = len(errs)
    return {"method": method, "n": n, "refused": refused,
            "mae": (sum(errs) / n) if n else None,
            "wape": (sum(errs) / actual_sum) if n and actual_sum > 0 else None,
            "bias": (signed / n) if n else None,
            "coverage": (covered / n) if n else None, "nominal_level": level}


# ---------------------------------------------------------------------------------------------
# Synthetic history (for backtests and tests; clearly not real venue data)
# ---------------------------------------------------------------------------------------------
HOURLY_PROFILE = {11: 0.3, 12: 0.8, 13: 1.0, 14: 0.5, 17: 0.4, 18: 0.9, 19: 1.0, 20: 0.9,
                  21: 0.5, 22: 0.2}
WEEKDAY_FACTOR = (0.7, 0.75, 0.8, 0.95, 1.3, 1.5, 1.0)   # Mon..Sun


def _poisson(rng: random.Random, lam: float) -> int:
    if lam <= 0:
        return 0
    if lam > 30:
        return max(0, round(rng.gauss(lam, math.sqrt(lam))))
    lim, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= lim:
            return k
        k += 1


def synthetic_history(days: int, *, start_day: int = date(2026, 1, 5).toordinal(), seed: int = 0,
                      base: float = 40.0, weekly_trend: float = 0.0,
                      disruption_prob: float = 0.04, day_level_sd: float = 0.08) -> History:
    """Generate hourly covers: weekday x hour profile, Poisson noise, per-day level noise,
    optional linear weekly trend (fraction per week) and rare disruption days (x0.3-0.6).
    Deterministic for a given seed. The true generating process is known, so error is
    attributable; real venues will be noisier and less regular.
    """
    rng = random.Random(seed)
    out: History = {}
    for i in range(days):
        d = start_day + i
        level = max(0.2, rng.gauss(1.0, day_level_sd)) * (1 + weekly_trend * i / 7)
        if rng.random() < disruption_prob:
            level *= rng.uniform(0.3, 0.6)
        for h, p in HOURLY_PROFILE.items():
            out[(d, h)] = float(_poisson(rng, base * p * WEEKDAY_FACTOR[_weekday(d)] * level))
    return out


# ---------------------------------------------------------------------------------------------
# Table-ready predictions for the host (survival-style remaining time)
# ---------------------------------------------------------------------------------------------
def party_bucket(party: int) -> str:
    return "1-2" if party <= 2 else "3-4" if party <= 4 else "5+"


class DwellModel:
    """Empirical dwell distributions per party-size bucket from completed visits.

    Assumptions: samples are completed dwells (seated to vacated); visits still in progress are
    unseen, which biases dwell slightly short. Dwells <= 0 or > ``max_dwell_s`` are dropped. Use
    the same daypart and weekday data where you can; this class does not segment by itself.
    """

    def __init__(self, samples: list[tuple[int, float]], max_dwell_s: float = 6 * 3600.0):
        self.by_bucket: dict[str, list[float]] = {}
        for party, dw in samples:
            if dw is None or not (0 < dw <= max_dwell_s):
                continue
            self.by_bucket.setdefault(party_bucket(party), []).append(float(dw))
        self.all = sorted(x for xs in self.by_bucket.values() for x in xs)
        for xs in self.by_bucket.values():
            xs.sort()

    def remaining(self, party: int, elapsed_s: float, *, min_n: int = 8,
                  lo_q: float = 0.2, hi_q: float = 0.8) -> dict:
        """Remaining-time estimate given the party has already sat ``elapsed_s``.

        Survival-style: condition on dwell > elapsed (only samples that lasted at least this
        long), remaining = dwell - elapsed; report median with the lo_q..hi_q range. If the
        party's bucket has fewer than ``min_n`` conditional samples, the pooled all-party
        distribution is used (``pooled`` True); if that is also thin, or the party has outlasted
        every sample, it returns no estimate (``overdue`` True in the latter case) rather than a
        made-up number. Assumes dwell is independent of anything not in the bucket.
        """
        if elapsed_s < 0:
            raise ValueError("elapsed_s must be >= 0")
        for pooled, xs in ((False, self.by_bucket.get(party_bucket(party), [])),
                           (True, self.all)):
            rem = [x - elapsed_s for x in xs if x > elapsed_s]
            if len(rem) >= min_n:
                return {"ok": True, "median_s": percentile(rem, 0.5),
                        "low_s": percentile(rem, lo_q), "high_s": percentile(rem, hi_q),
                        "n": len(rem), "pooled": pooled, "overdue": False}
        overdue = bool(self.all) and elapsed_s >= self.all[-1]
        return {"ok": False, "n": len([x for x in self.all if x > elapsed_s]), "overdue": overdue,
                "reason": ("party has stayed longer than any recorded visit" if overdue
                           else "not enough comparable visits")}


def table_ready_predictions(tables: list[dict], model: DwellModel, *, reset_s: float = 120.0,
                            **kw) -> list[dict]:
    """Per-table 'ready in' estimates for the host. ``tables``: dicts with table, party,
    elapsed_s and optional seats. Adds ``reset_s`` (clear and reset time) to every estimate.
    Returns the list sorted by soonest median; tables with no estimate go last. Estimates are
    ranges; show them as ranges."""
    out = []
    for t in tables:
        r = model.remaining(t["party"], t["elapsed_s"], **kw)
        row = {"table": t["table"], "seats": t.get("seats"), **r}
        if r["ok"]:
            for k in ("median_s", "low_s", "high_s"):
                row[k] += reset_s
        out.append(row)
    out.sort(key=lambda r: (not r["ok"], r.get("median_s", 0.0), str(r["table"])))
    return out


def quote_wait(predictions: list[dict], party: int, ahead: int = 0,
               free_now: list[dict] | None = None) -> dict:
    """Wait quote for a waiting party with ``ahead`` same-size parties in front of it.

    Uses tables with seats >= party (unknown seats are excluded, not assumed). Tables free now
    count as zero wait. The quote is the (ahead+1)-th soonest eligible table; low/high use the
    same rank on the low/high estimates, which is a rough range (it ignores correlation and
    table combining and treats each table as seating one party). Returns ok False when there
    are not enough eligible tables with estimates; never invents a number.
    """
    rows = [(0.0, 0.0, 0.0) for t in (free_now or []) if (t.get("seats") or 0) >= party]
    rows += [(p["low_s"], p["median_s"], p["high_s"]) for p in predictions
             if p.get("ok") and (p.get("seats") or 0) >= party]
    if len(rows) <= ahead:
        return {"ok": False, "reason": "not enough eligible tables with estimates"}
    lows = sorted(r[0] for r in rows)[ahead]
    meds = sorted(r[1] for r in rows)[ahead]
    highs = sorted(r[2] for r in rows)[ahead]
    return {"ok": True, "median_s": meds, "low_s": lows, "high_s": highs}
