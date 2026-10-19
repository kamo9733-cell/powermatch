import pytest

from tablesight.capacity import (
    CapacityConfig,
    CountSample,
    evaluate_capacity,
    rebalance_hint,
    section_loads,
    suggest_seating,
)

CFG = CapacityConfig(licensed=100, confirm_s=30, hold_s=120)


def run(counts, step=15.0, **kw):
    return evaluate_capacity([CountSample(i * step, c, **kw) for i, c in enumerate(counts)], CFG)


def test_thresholds():
    assert CFG.enter("near") == 90 and CFG.enter("at") == 100 and CFG.enter("over") == 101
    assert CFG.exit("over") == 96
    with pytest.raises(ValueError):
        CapacityConfig(licensed=0)
    tiny = CapacityConfig(licensed=1)
    assert tiny.enter("near") <= tiny.enter("at")


def test_empty_and_single_sample():
    r = run([])
    assert r["state"] == "ok" and r["transitions"] == [] and r["samples"] == 0
    assert run([120])["state"] == "ok"             # one sample cannot be confirmed


def test_brief_spike_does_not_alert_but_sustained_does():
    assert run([50, 105, 50, 50])["transitions"] == []
    r = run([50, 105, 105, 105])
    assert [t["to"] for t in r["transitions"]] == ["over"] and r["state"] == "over"


def test_hysteresis_flicker_at_limit():
    counts = [95, 95, 95] + [101, 99, 101, 99, 101, 99, 101, 99, 101, 100, 101] * 3
    r = run(counts)
    # flicker across the limit never holds a level long enough to confirm: no alert spam
    assert [t["to"] for t in r["transitions"]] == ["near"]
    # a sustained breach right after the flicker is still caught
    assert run(counts + [103] * 4)["state"] == "over"


def test_clears_only_after_hold_below_exit():
    r = run([101] * 4 + [97] * 20)                 # 97 >= exit(over)=96: stays over
    assert r["state"] == "over"
    r = run([101] * 4 + [80] * 4)                  # only 45s below exit: not yet
    assert r["state"] == "over"
    r = run([101] * 4 + [80] * 12)
    assert r["state"] == "ok" or r["state"] == "near"
    assert r["transitions"][-1]["to"] in ("ok", "near")


def test_stale_negative_implausible_skipped():
    r = evaluate_capacity([CountSample(0, 500), CountSample(15, -3), CountSample(30, 105, stale=True),
                           CountSample(45, 105, stale=True)], CFG)
    assert r["skipped"] == {"stale": 2, "negative": 1, "implausible": 1}
    assert r["state"] == "ok"


def test_possible_breach_from_uncertainty():
    r = run([98, 98, 98], uncertainty=5)
    assert r["possible_breach_samples"] == 3 and r["state"] in ("near", "ok")


def test_unsorted_and_duplicate_timestamps():
    s = [CountSample(30, 105), CountSample(0, 105), CountSample(15, 105), CountSample(15, 105)]
    assert evaluate_capacity(s, CFG)["state"] == "over"


# ---- sections ---------------------------------------------------------------------------
def secs():
    return {
        "A": {"servers": 1, "tables": {"1": {"seats": 4, "party": 4}, "2": {"seats": 4, "party": 4},
                                       "3": {"seats": 2, "party": 0}}},
        "B": {"servers": 1, "tables": {"4": {"seats": 4, "party": 0}, "5": {"seats": 2, "party": 2,
                                                                       "needs_attention": True}}},
        "C": {"servers": 0, "tables": {"6": {"seats": 6, "party": 0}}},
    }


def test_section_loads_and_unstaffed():
    L = section_loads(secs())
    assert L["A"]["load"] == 8 and L["B"]["load"] == 4 and L["C"]["unstaffed"]
    assert L["C"]["load"] is None


def test_suggest_prefers_light_staffed_section_with_fit():
    r = suggest_seating(secs(), 3)
    assert r["suggestion"] == "B" and r["balanced"] is False
    assert any("Unstaffed" in n for n in r["notes"])
    assert suggest_seating(secs(), 2)["suggestion"] == "B"
    none = suggest_seating(secs(), 7)
    assert none["suggestion"] is None


def test_balanced_floor_says_so_and_ties_are_deterministic():
    even = {"X": {"servers": 1, "tables": {"1": {"seats": 4, "party": 2}, "2": {"seats": 4}}},
            "W": {"servers": 1, "tables": {"3": {"seats": 4, "party": 2}, "4": {"seats": 4}}}}
    r = suggest_seating(even, 2)
    assert r["balanced"] and r["suggestion"] == "W"
    with pytest.raises(ValueError):
        suggest_seating(even, 0)
    assert suggest_seating({}, 2)["suggestion"] is None


def test_rebalance_hint_team_wording_and_edge_cases():
    h = rebalance_hint(secs(), min_gap=3)
    assert h["heavy"] == "A" and h["light"] == "B"
    assert "performance" not in h["message"] and h["gap"] == 4
    assert rebalance_hint(secs(), min_gap=10) is None
    assert rebalance_hint({"A": secs()["A"]}) is None
    assert rebalance_hint({}) is None


def test_bad_party_reading_clipped():
    s = {"A": {"servers": 1, "tables": {"1": {"seats": 2, "party": 50}}}}
    L = section_loads(s)
    assert L["A"]["open_covers"] == 4 and L["A"]["suspect_tables"] == 1
