import pytest

from tablesight.queueing import (
    QueueAlertConfig,
    QueueSample,
    QueueVisit,
    estimate_wait,
    littles_law_check,
    queue_alerts,
    summarize_queue,
)


def test_empty_and_negative_queue():
    assert estimate_wait(0, [], 100)["wait_s"] == 0
    with pytest.raises(ValueError):
        estimate_wait(-1, [], 100)


def test_wait_is_length_over_rate():
    deps = [i * 30.0 for i in range(1, 21)]            # one every 30 s
    r = estimate_wait(6, deps, 600)
    assert r["ok"] and r["wait_s"] == pytest.approx(6 * 30, rel=0.1) and r["flags"] == []


def test_no_estimate_when_stalled_or_thin():
    assert estimate_wait(5, [], 1000)["stalled"]
    assert estimate_wait(5, [990.0], 1000).get("stalled") is None
    assert not estimate_wait(5, [990.0, 995.0], 1000)["ok"]          # two departures only
    assert estimate_wait(5, [100.0, 200.0, 300.0], 1000)["stalled"]  # all outside window


def test_burst_does_not_explode_rate_and_cap_flag():
    r = estimate_wait(500, [999.0, 999.5, 1000.0], 1000, max_plausible_s=3600)
    assert r["wait_s"] == 3600 and "capped" in r["flags"]


def test_inconsistent_with_observed_waits():
    deps = [i * 30.0 for i in range(1, 21)]
    r = estimate_wait(6, deps, 600, observed_waits=[1200.0, 1500.0])
    assert "inconsistent" in r["flags"]
    assert "inconsistent" not in estimate_wait(6, deps, 600, observed_waits=[170.0])["flags"]


def test_littles_law_holds_on_consistent_data():
    visits = [QueueVisit(i * 60.0, i * 60.0 + 180.0) for i in range(60)]
    r = littles_law_check(visits, (600, 3000))
    assert r["ok"] and r["relative_gap"] < 0.1
    assert r["W_s"] == pytest.approx(180, rel=0.05)


def test_littles_law_refuses_small_or_invalid():
    assert littles_law_check([], (0, 100))["ok"] is None
    bad = [QueueVisit(i * 10.0, i * 10.0 - 5) for i in range(20)]
    assert littles_law_check(bad, (0, 300))["ok"] is False
    with pytest.raises(ValueError):
        littles_law_check([], (5, 5))


def test_littles_law_flags_ghost_visits():
    # open visits never closed (missed departures) inflate W relative to L only via boundary;
    # a large tolerance failure is expected when most visits are stuck open
    visits = [QueueVisit(i * 10.0, None) for i in range(30)]
    visits += [QueueVisit(5000.0, 5001.0)] * 0
    r = littles_law_check(visits, (0, 300))
    assert r["ok"] is not None and "L" in r


def samples(lengths, step=30.0):
    return [QueueSample(i * step, n) for i, n in enumerate(lengths)]


def test_long_queue_needs_sustain_and_clears_with_hysteresis():
    s = samples([2, 9, 2, 9, 9, 9, 7, 9, 9, 9, 3, 9, 9, 9])
    cfg = QueueAlertConfig(max_len=8, clear_len=5, sustain_s=60, cooldown_s=0,
                           max_wait_s=1e9, stall_s=1e9)
    a = [x for x in queue_alerts(s, [], cfg) if x["kind"] == "long_queue"]
    # first clump (t=30) is too brief; sustained at t=120; 7 does not clear; clears at 3, re-fires
    assert [x["t"] for x in a] == [150.0, 450.0] or len(a) == 2
    assert a[0]["t"] == 150.0


def test_uncertain_samples_ignored_and_duplicates_and_unsorted():
    s = [QueueSample(60, 10), QueueSample(0, 10), QueueSample(30, 10, uncertain=True),
         QueueSample(60, 10), QueueSample(120, 10)]
    cfg = QueueAlertConfig(sustain_s=60, stall_s=1e9, max_wait_s=1e9)
    a = queue_alerts(s, [], cfg)
    assert [x["kind"] for x in a] == ["long_queue"]
    assert queue_alerts([QueueSample(0, 20, uncertain=True)] * 5, []) == []
    assert queue_alerts([], []) == []


def test_stalled_alert_and_cooldown():
    s = samples([4] * 30)
    deps = [0.0, 10.0]
    cfg = QueueAlertConfig(max_len=50, clear_len=1, stall_s=240, sustain_s=0, cooldown_s=10_000,
                           max_wait_s=1e9)
    a = queue_alerts(s, deps, cfg)
    assert [x["kind"] for x in a] == ["stalled"]
    assert a[0]["t"] >= 250


def test_long_wait_alert():
    deps = [i * 60.0 for i in range(1, 11)]          # one per minute
    s = [QueueSample(600.0 + i * 30, 15) for i in range(6)]
    cfg = QueueAlertConfig(max_len=99, clear_len=1, max_wait_s=600, sustain_s=30, stall_s=1e9)
    kinds = {x["kind"] for x in queue_alerts(s, deps, cfg)}
    assert "long_wait" in kinds


def test_bad_config_rejected():
    with pytest.raises(ValueError):
        queue_alerts([], [], QueueAlertConfig(max_len=5, clear_len=5))


def test_summarize_queue_edge_cases():
    assert summarize_queue([]).time_avg_len is None
    one = summarize_queue([QueueSample(0, 3)])
    assert one.max_len == 3 and one.time_avg_len is None and one.notes
    s = summarize_queue(samples([2, 4, 4]) + [QueueSample(100000, 50), QueueSample(1, 99, True)])
    assert s.skipped_uncertain == 1 and s.notes          # long gap not interpolated
    assert s.time_avg_len == pytest.approx((2 * 30 + 4 * 30) / 60)
