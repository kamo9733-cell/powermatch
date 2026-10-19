import math
import time
from datetime import date

import pytest

from tablesight.forecast import (
    DwellModel,
    backtest,
    ewma_ratio,
    quote_wait,
    seasonal_naive,
    synthetic_history,
    table_ready_predictions,
)

START = date(2026, 1, 5).toordinal()   # Monday


def flat_history(days, value=50.0, hour=12):
    return {(START + i, hour): value for i in range(days)}


def test_refuses_with_insufficient_history():
    f = seasonal_naive({}, START + 100, 12)
    assert not f.ok and f.point is None and "comparable" in f.reason
    h = flat_history(15)   # two Mondays before day 14 -> only 2 comparable
    assert not seasonal_naive(h, START + 14, 12).ok
    assert not ewma_ratio({}, START + 100, 12).ok


def test_one_sample_refused_and_constant_history_has_width():
    assert not seasonal_naive({(START, 12): 40.0}, START + 7, 12).ok
    f = seasonal_naive(flat_history(30), START + 28, 12, min_n=3)
    assert f.ok and f.point == 50 and f.low < 50 < f.high   # Poisson floor, never zero width


def test_only_same_weekday_and_never_future():
    h = flat_history(60)
    for i in range(60):
        if date.fromordinal(START + i).weekday() == 5:
            h[(START + i, 12)] = 500.0                      # Saturdays are huge
    mon = seasonal_naive(h, START + 56, 12)
    assert mon.point == 50
    h[(START + 70, 12)] = 9999.0                            # future data must be ignored
    assert seasonal_naive(h, START + 63, 12).point == 50


def test_outlier_day_barely_moves_median_and_garbage_dropped():
    h = flat_history(60)
    h[(START + 49, 12)] = 0.0                               # storm day
    h[(START + 42, 12)] = float("nan")
    h[(START + 35, 12)] = -3.0
    f = seasonal_naive(h, START + 56, 12)
    assert f.point == 50 and f.n == 6   # 8 prior Mondays within window minus nan and negative


def test_exclude_days_and_level_validation():
    h = flat_history(60)
    ex = frozenset(START + 7 * k for k in range(7))
    assert not seasonal_naive(h, START + 56, 12, exclude=ex, min_n=3).ok
    with pytest.raises(ValueError):
        seasonal_naive(h, START + 56, 12, level=0.77)


def test_interval_widens_with_noise():
    calm = synthetic_history(120, seed=1, base=400, day_level_sd=0.02, disruption_prob=0)
    noisy = synthetic_history(120, seed=1, base=400, day_level_sd=0.4, disruption_prob=0)
    d = START + 119
    a, b = seasonal_naive(calm, d, 19), seasonal_naive(noisy, d, 19)
    assert (b.high - b.low) > (a.high - a.low)


def test_synthetic_deterministic_and_nonnegative():
    a, b = synthetic_history(30, seed=5), synthetic_history(30, seed=5)
    assert a == b and a != synthetic_history(30, seed=6)
    assert all(v >= 0 and float(v).is_integer() for v in a.values())
    assert synthetic_history(0) == {}


def test_backtest_reports_honest_numbers_and_refusals():
    h = synthetic_history(140, seed=11, disruption_prob=0.05)
    days = list(range(START + 100, START + 140))
    r = backtest(h, days, "seasonal_naive")
    assert r["n"] > 200 and r["refused"] == 0
    assert 0 < r["wape"] < 0.5
    assert 0.55 < r["coverage"] <= 1.0     # nominal 0.8; checked loosely, reported as measured
    early = backtest(h, [START + 3], "seasonal_naive")
    assert early["n"] == 0 and early["refused"] > 0 and early["wape"] is None


def test_ewma_beats_naive_on_trend_and_is_fast_enough():
    h = synthetic_history(150, seed=3, weekly_trend=0.05, disruption_prob=0.0)
    days = list(range(START + 110, START + 140))
    t0 = time.time()
    a = backtest(h, days, "seasonal_naive")
    b = backtest(h, days, "ewma_ratio")
    assert time.time() - t0 < 30
    assert b["wape"] < a["wape"]
    assert abs(b["bias"]) < abs(a["bias"])
    assert 0.0 <= b["coverage"] <= 1.0


def test_ewma_ratio_valid_interval_and_alpha_check():
    h = synthetic_history(100, seed=2)
    f = ewma_ratio(h, START + 99, 19)
    assert f.ok and f.low <= f.point <= f.high and f.low >= 0
    with pytest.raises(ValueError):
        ewma_ratio(h, START + 99, 19, alpha=0)


# ---- dwell / table-ready ----------------------------------------------------------------
def samples():
    return [(2, 3000 + 60 * i) for i in range(20)] + [(5, 5000 + 100 * i) for i in range(10)]


def test_remaining_is_conditional_on_elapsed():
    m = DwellModel(samples())
    young = m.remaining(2, 600)
    old = m.remaining(2, 3500)
    assert young["ok"] and old["ok"]
    assert young["low_s"] <= young["median_s"] <= young["high_s"]
    assert old["median_s"] < young["median_s"]
    assert young["n"] == 20 and not young["pooled"]


def test_remaining_falls_back_to_pooled_then_refuses():
    m = DwellModel([(2, 3000 + i) for i in range(20)] + [(8, 5000), (8, 5200)])
    r = m.remaining(8, 100)
    assert r["ok"] and r["pooled"]
    over = m.remaining(2, 99999)
    assert not over["ok"] and over["overdue"]
    assert not DwellModel([]).remaining(2, 10)["ok"]
    assert not DwellModel([(2, 100.0)]).remaining(2, 10)["ok"]
    with pytest.raises(ValueError):
        m.remaining(2, -1)


def test_dwell_model_drops_garbage():
    m = DwellModel([(2, -5), (2, 0), (2, 10 * 3600), (2, None), (2, 2000)])
    assert m.all == [2000.0]


def test_predictions_sorted_and_quote():
    m = DwellModel(samples())
    tables = [{"table": "A", "party": 2, "elapsed_s": 600, "seats": 2},
              {"table": "B", "party": 2, "elapsed_s": 3000, "seats": 4},
              {"table": "C", "party": 2, "elapsed_s": 99999, "seats": 4}]
    p = table_ready_predictions(tables, m, reset_s=100)
    assert [r["table"] for r in p] == ["B", "A", "C"] and not p[-1]["ok"]
    assert p[0]["median_s"] >= 100
    q = quote_wait(p, 3)
    assert q["ok"] and q["low_s"] <= q["median_s"] <= q["high_s"]
    assert not quote_wait(p, 3, ahead=1)["ok"]                     # only one eligible table
    assert quote_wait(p, 3, ahead=1, free_now=[{"seats": 4}])["ok"]
    assert not quote_wait(p, 9)["ok"]
    assert not quote_wait([], 2)["ok"]
    assert math.isfinite(q["median_s"])
