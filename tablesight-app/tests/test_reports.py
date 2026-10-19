from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from tablesight.analytics import business_day
from tablesight.reports import (
    PosEvent,
    business_day_of,
    compare_like_with_like,
    daypart_of,
    net_revenue,
    occupied_seat_hours,
    rev_per_seat_hour,
    shift_report,
    split_business_days,
    summarize,
)
from tablesight.table import Event

NY = "America/New_York"


def ts(y, mo, d, h=0, mi=0, tz="UTC"):
    return datetime(y, mo, d, h, mi, tzinfo=ZoneInfo(tz)).timestamp()


def visit(table, t0, dwell, party=2, visits=(300,), staff=None):
    ev = [Event(t0, table, "seated", {"party": party})]
    for dt in visits:
        ev.append(Event(t0 + dt, table, "staff_visit", {"staff": staff} if staff else {}))
    ev.append(Event(t0 + dwell + 60, table, "vacated", {"dwell": dwell, "party": party}))
    return ev


def day_events(t0, n=6, dwell=3000.0):
    out = []
    for i in range(n):
        out += visit(f"T{i}", t0 + i * 600, dwell + i * 60)
    return out


# ---- shift report -----------------------------------------------------------------------
def test_empty_report_is_valid_and_honest():
    r = shift_report([])
    assert r["visits"] == 0 and r["turn"]["n"] == 0 and r["turn"]["median_s"] is None
    assert r["turn"]["reliable"] is False
    assert r["alerts"]["ack_rate"] is None
    assert r["framing"]["attribution"] == "insufficient data"
    assert r["scope"] == "team"


def test_one_sample_is_flagged_unreliable():
    r = shift_report(visit("T1", 0, 2400))
    assert r["turn"]["n"] == 1 and r["turn"]["median_s"] == 2400
    assert not r["turn"]["reliable"] and not r["turn"]["p90_reliable"]
    assert r["greet"]["median_s"] == 300 and not r["greet"]["reliable"]


def test_metrics_basic_and_outlier_robust():
    evs = []
    for i in range(10):
        evs += visit(f"T{i}", i * 5000, 3000, visits=(200, 800, 1500))
    evs += visit("TX", 100000, 40 * 3600)           # sensor artefact: 40h dwell
    r = shift_report(evs)
    assert r["turn"]["median_s"] == 3000 and r["turn"]["reliable"] and r["turn"]["p90_reliable"]
    assert r["excluded"]["dwell_implausible"] == 1
    assert r["checkback_gap"]["median_s"] == 650
    assert sum(r["greet"]["distribution"].values()) == 11


def test_dwell_outlier_does_not_move_median():
    base = [d for i in range(9) for d in visit(f"T{i}", i * 5000, 3000)]
    r1 = shift_report(base)
    r2 = shift_report(base + visit("T9", 90000, 20000))   # plausible but long
    assert abs(r2["turn"]["median_s"] - r1["turn"]["median_s"]) <= 1
    assert r2["turn"]["max_s"] == 20000


def test_alerts_acknowledged_and_walkaways():
    evs = visit("T1", 0, 3000) + [
        Event(500, "T1", "needs_attention", {"waited": 500}),
        Event(900, "T2", "walk_away", {"waited": 600}),
        Event(950, "T3", "walk_away"),
    ]
    alerts = [{"t": 510, "tables": ["T1"]}, {"t": 900, "tables": ["T2"]}]
    acks = [{"t": 530, "table": "T1"}, {"t": 100, "table": "T2"}]   # second ack predates alert
    r = shift_report(evs, alerts=alerts, acks=acks)
    assert r["alerts"]["detected"] == 1 and r["alerts"]["sent"] == 2
    assert r["alerts"]["acknowledged"] == 1 and r["alerts"]["ack_rate"] == 0.5
    assert not r["alerts"]["reliable"]
    assert r["walk_aways"]["n"] == 2 and r["walk_aways"]["wait_before_leaving"]["n"] == 1


def test_one_ack_not_credited_to_two_alerts():
    alerts = [{"t": 10, "tables": ["T1"]}, {"t": 20, "tables": ["T1"]}]
    r = shift_report([], alerts=alerts, acks=[{"t": 30, "table": "T1"}])
    assert r["alerts"]["acknowledged"] == 1


def test_systemic_load_related_framing_never_blames_individual():
    evs = []
    # quiet period: single tables greeted fast; rush: many overlapping tables greeted slowly
    for i in range(6):
        evs += visit(f"Q{i}", i * 10000, 1500, visits=(60,))
    for i in range(8):
        evs += visit(f"R{i}", 100000 + i * 30, 5000, visits=(700,))
    r = shift_report(evs)
    assert r["framing"]["attribution"] == "systemic: load-related"
    assert "individual" not in r["framing"]["finding"].replace("not at individuals", "")
    assert "staff" not in r


def test_staff_level_gated_suppressed_and_caveated():
    evs = []
    for i in range(6):
        evs += visit(f"A{i}", i * 5000, 2000, staff="alex")
    evs += visit("B0", 99999, 2000, staff="bo")
    assert "staff" not in shift_report(evs)
    r = shift_report(evs, allow_staff_level=True)
    assert r["staff"]["bo"]["suppressed"] and "median_s" not in r["staff"]["bo"]
    assert r["staff"]["alex"]["median_s"] == 300 and "caveat" in r["staff"]["alex"]
    assert list(r["staff"]) == sorted(r["staff"]) and r["staff_caveat"]


def test_window_and_validation():
    evs = visit("T1", 0, 1000) + visit("T2", 10_000, 1000)
    r = shift_report(evs, window=(5_000, 20_000))
    assert r["visits"] == 1 and r["hours"] == pytest.approx(15_000 / 3600)
    with pytest.raises(ValueError):
        shift_report(evs, window=(5, 5))


def test_missed_vacated_and_stray_events_do_not_crash():
    evs = [Event(0, "T1", "seated", {"party": 2}), Event(100, "T1", "seated", {"party": 3}),
           Event(200, "T9", "vacated", {"dwell": 50}), Event(300, "T1", "staff_visit")]
    r = shift_report(evs)
    assert r["visits"] == 2 and r["turn"]["n"] == 0


def test_summarize_basic():
    assert summarize([])["n"] == 0
    s = summarize([1, 2, 3, 4, 100])
    assert s["median_s"] == 3 and s["reliable"] and not s["p90_reliable"]


# ---- calendar semantics -----------------------------------------------------------------
def test_midnight_crossing_matches_existing_business_day_helper():
    fri = date(2026, 6, 5).toordinal()
    sat_1am = ts(2026, 6, 6, 1, 0, NY)
    assert business_day_of(sat_1am, NY) == fri == business_day(1.0, fri + 1)
    assert business_day_of(ts(2026, 6, 6, 5, 0, NY), NY) == fri + 1
    assert daypart_of(sat_1am, NY) == "late"
    assert daypart_of(ts(2026, 6, 5, 12, 0, NY), NY) == "lunch"


def test_dst_fall_back_both_1am_hours_same_business_day():
    sat = date(2026, 10, 31).toordinal()
    a = datetime(2026, 11, 1, 1, 30, tzinfo=ZoneInfo(NY), fold=0).timestamp()
    b = datetime(2026, 11, 1, 1, 30, tzinfo=ZoneInfo(NY), fold=1).timestamp()
    assert b - a == 3600
    assert business_day_of(a, NY) == business_day_of(b, NY) == sat
    assert business_day_of(ts(2026, 11, 1, 6, 0, NY), NY) == sat + 1


def test_split_business_days_keeps_after_midnight_with_previous_day():
    evs = [Event(ts(2026, 6, 5, 23, 0, NY), "T1", "seated"),
           Event(ts(2026, 6, 6, 0, 30, NY), "T1", "vacated", {"dwell": 5000}),
           Event(ts(2026, 6, 6, 18, 0, NY), "T2", "seated")]
    days = split_business_days(evs, NY)
    assert sorted(len(v) for v in days.values()) == [1, 2]


# ---- like-with-like ---------------------------------------------------------------------
def weekly_history(start, weeks, dwell_fn, tz="UTC", hour=12):
    evs = []
    for w in range(weeks):
        d = date.fromordinal(start.toordinal() + 7 * w)
        evs += day_events(ts(d.year, d.month, d.day, hour, 0, tz), 6, dwell_fn(w))
    return evs


def test_compare_same_weekday_and_daypart_only():
    start = date(2026, 5, 4)   # Monday
    evs = weekly_history(start, 4, lambda w: 3000)
    # a slow Saturday must not pollute Monday reference
    sat = date(2026, 5, 9)
    evs += day_events(ts(sat.year, sat.month, sat.day, 12), 6, 9000)
    target = date(2026, 6, 1)
    evs += day_events(ts(target.year, target.month, target.day, 12), 6, 3100)
    r = compare_like_with_like(evs, target.toordinal(), daypart="lunch")
    assert r["comparable"] and r["reference_days"] == 4 and r["verdict"] == "within normal range"
    assert r["reference_median_s"] < 4000


def test_compare_flags_slower_and_refuses_when_thin():
    start = date(2026, 5, 4)
    evs = weekly_history(start, 4, lambda w: 3000)
    target = date(2026, 6, 1)
    evs += day_events(ts(target.year, target.month, target.day, 12), 6, 8000)
    r = compare_like_with_like(evs, target.toordinal())
    assert r["verdict"] == "slower than usual"
    assert compare_like_with_like(evs, target.toordinal(), min_days=10)["comparable"] is False
    assert compare_like_with_like([], target.toordinal())["comparable"] is False
    with pytest.raises(ValueError):
        compare_like_with_like(evs, target.toordinal(), daypart="brunch")


def test_compare_excludes_holidays_and_thin_days():
    start = date(2026, 5, 4)
    evs = weekly_history(start, 4, lambda w: 3000)
    target = date(2026, 6, 1)
    evs += day_events(ts(target.year, target.month, target.day, 12), 6, 3000)
    ex = frozenset({date(2026, 5, 11).toordinal(), date(2026, 5, 18).toordinal()})
    r = compare_like_with_like(evs, target.toordinal(), exclude_days=ex, min_days=3)
    assert r["comparable"] is False and r["reference_days"] == 2
    r2 = compare_like_with_like(evs, target.toordinal(), min_n_per_day=7)
    assert r2["comparable"] is False and r2["skipped_thin_days"] == 4


def test_compare_across_dst_week():
    # Mondays around the March 2026 spring-forward: same local lunch hour, same business day logic
    start = date(2026, 2, 16)
    evs = weekly_history(start, 4, lambda w: 3000, tz=NY)
    target = date(2026, 3, 16)
    evs += day_events(ts(target.year, target.month, target.day, 12, 0, NY), 6, 3050)
    r = compare_like_with_like(evs, target.toordinal(), tz=NY, daypart="lunch")
    assert r["comparable"] and r["reference_days"] == 4


# ---- revenue ----------------------------------------------------------------------------
def test_revpash_dst_25_hour_day():
    lo, hi = ts(2026, 11, 1, 0, 0, NY), ts(2026, 11, 2, 0, 0, NY)
    assert (hi - lo) / 3600 == 25
    pos = [PosEvent(lo + 3600, "c1", 1000.0)]
    r = rev_per_seat_hour(pos, 40, (lo, hi))
    assert r["available_seat_hours"] == 1000 and r["revpash"] == pytest.approx(1.0)


def test_revpash_spring_23h_and_closed_seats():
    lo, hi = ts(2026, 3, 8, 0, 0, NY), ts(2026, 3, 9, 0, 0, NY)
    assert (hi - lo) / 3600 == 23
    r = rev_per_seat_hour([PosEvent(lo + 10, "c", 230.0)], 10, (lo, hi), closed_seat_hours=0.0)
    assert r["revpash"] == pytest.approx(1.0)


def test_pos_dedupe_refunds_rejects_and_refusal():
    pos = [PosEvent(10, "a", 100.0), PosEvent(11, "a", 100.0), PosEvent(12, "b", 30.0, "refund"),
           PosEvent(13, "c", -5.0), PosEvent(14, "d", float("nan")), PosEvent(15, "e", 5, "gift"),
           PosEvent(500, "z", 999.0)]
    n = net_revenue(pos, (0, 100))
    assert n == {"revenue": 70.0, "duplicates_ignored": 1, "rejected": 3}
    assert rev_per_seat_hour([], 10, (0, 100))["revpash"] is None   # 0.28 seat-hours
    r = rev_per_seat_hour(pos, 1, (0, 100))
    assert r["revpash"] is None and "small" in r["reason"]
    with pytest.raises(ValueError):
        rev_per_seat_hour(pos, 0, (0, 100))
    with pytest.raises(ValueError):
        rev_per_seat_hour(pos, 5, (100, 100))


def test_occupied_seat_hours_clips_and_counts_open():
    evs = [Event(0, "T1", "seated", {"party": 2}), Event(3600, "T1", "vacated", {"dwell": 3600}),
           Event(1800, "T2", "seated", {"party": 4}),            # still open
           Event(0, "T3", "seated", {})]                          # unknown party
    r = occupied_seat_hours(evs, (1800, 7200))
    assert r["guest_hours"] == pytest.approx(2 * 0.5 + 4 * 1.5)
    assert r["open_visits"] == 2 and r["unknown_party"] == 1
    assert occupied_seat_hours([], (0, 10))["guest_hours"] == 0
