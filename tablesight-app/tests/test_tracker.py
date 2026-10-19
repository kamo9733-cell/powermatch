"""Tracker unit tests + the CI gate: ID-switch rate must not regress past the stored baseline.

The gate runs on SYNTHETIC scenes with fixed seeds (tablesight/synth/baseline.json). If you
change the tracker on purpose, re-record with `python -m tablesight.synth --write-baseline`
and explain the change in docs/EVAL_BASELINE.md; do not just loosen the tolerance.
"""
import itertools

import pytest

from tablesight.perception import ByteTracker, IouTracker, RawDet, hungarian
from tablesight.synth import SCENARIOS, evaluate
from tablesight.synth.benchmark import GATE_SEEDS, load_baseline, pooled

REL_TOL, ABS_TOL = 0.10, 0.25  # allowed regression: 10% + 0.25 switches per 1000 boxes


def test_hungarian_matches_brute_force():
    import random
    rnd = random.Random(1)
    for n, m in [(3, 3), (2, 4), (4, 2), (5, 5)]:
        c = [[rnd.random() for _ in range(m)] for _ in range(n)]
        got = sum(c[i][j] for i, j in hungarian(c))
        k = min(n, m)
        best = min(
            sum(c[i][j] for i, j in zip(rows, cols, strict=True))
            for rows in itertools.combinations(range(n), k)
            for cols in itertools.permutations(range(m), k))
        assert abs(got - best) < 1e-9


def test_hungarian_empty():
    assert hungarian([]) == [] and hungarian([[]]) == []


def test_bytetrack_keeps_id_through_short_occlusion():
    tr = ByteTracker(min_hits=2, max_age=10)
    ids = set()
    for i in range(30):
        dets = [] if 10 <= i < 14 else [RawDet((i * 3, 0, i * 3 + 40, 100), .9)]
        ids |= {t for t, _ in tr.update(dets)}
    assert len(ids) == 1


def test_bytetrack_separates_two_people_and_returns_det_boxes():
    tr = ByteTracker(min_hits=2)
    for _ in range(5):
        dets = [RawDet((0, 0, 40, 100), .9), RawDet((200, 0, 240, 100), .9)]
        out = tr.update(dets)
    assert len({t for t, _ in out}) == 2
    assert {b for _, b in out} == {d.box for d in dets}


def test_velocity_prediction_survives_fast_motion_greedy_iou_loses():
    def run(tr):
        ids = set()
        for i in range(25):  # 30 px/frame on a 40 px wide box: consecutive IoU is zero
            out = tr.update([RawDet((i * 30, 0, i * 30 + 40, 100), .9)])
            ids |= {t for t, _ in out}
        return ids
    # the first frames cannot be predicted (velocity unknown), so a constant-velocity tracker
    # may need one restart, but must settle on a single id afterwards
    assert len(run(ByteTracker(min_hits=2, iou_min=0.05))) <= 2
    assert len(run(IouTracker(min_hits=2))) == 0  # greedy IoU never even confirms the person


def test_low_confidence_detection_rescues_track_but_never_creates_one():
    tr = ByteTracker(min_hits=2)
    for _ in range(4):
        out = tr.update([RawDet((0, 0, 40, 100), .9)])
    tid = out[0][0]
    out = tr.update([RawDet((1, 0, 41, 100), .25)])  # blurry frame
    assert out and out[0][0] == tid
    tr2 = ByteTracker(min_hits=1)
    assert tr2.update([RawDet((0, 0, 40, 100), .25)]) == []


def test_unconfirmed_ghost_dies_quickly():
    tr = ByteTracker(min_hits=3, max_age=30)
    tr.update([RawDet((0, 0, 40, 100), .9)])
    tr.update([])
    tr.update([])
    assert tr._tracks == []


def test_colour_cue_keeps_identities_through_a_head_on_pass():
    # two people walk through each other (identical boxes at the midpoint); colour keeps ids apart
    tr = ByteTracker(min_hits=1, appearance_weight=0.9, iou_min=0.05)
    first = {}
    for i in range(21):
        xa, xb = i * 10, 200 - i * 10
        out = dict(tr.update([RawDet((xa, 0, xa + 40, 100), .9, (0.0, 0.8, 0.8)),
                              RawDet((xb, 0, xb + 40, 100), .9, (0.6, 0.8, 0.8))]))
        first.setdefault("ids", sorted(out))
        assert sorted(out) == first["ids"]
        if i != 10:  # at the midpoint the boxes coincide, so position cannot tell them apart
            assert (out[1][0], out[2][0]) == (xa, xb)


# ---- CI gate -------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def current():
    return {sc: evaluate(lambda: ByteTracker(min_hits=3), sc, GATE_SEEDS) for sc in SCENARIOS}


def test_baseline_file_matches_gate_config():
    b = load_baseline()
    assert b["synthetic"] is True and b["seeds"] == GATE_SEEDS
    assert set(b["trackers"]["bytetrack_style"]["scenarios"]) == set(SCENARIOS)


def test_id_switch_rate_does_not_regress(current):
    base = load_baseline()["trackers"]["bytetrack_style"]
    for sc, m in current.items():
        limit = base["scenarios"][sc]["switch_rate_per_1k"] * (1 + REL_TOL) + ABS_TOL
        assert m.switch_rate_per_1k <= limit, (
            f"ID-switch regression on synthetic scenario {sc!r}: "
            f"{m.switch_rate_per_1k:.2f}/1k > allowed {limit:.2f}/1k")
    overall = pooled(current)
    lim = base["overall"]["switch_rate_per_1k"] * (1 + REL_TOL) + ABS_TOL
    assert overall["switch_rate_per_1k"] <= lim
    assert overall["hota"] >= base["overall"]["hota"] - 0.02
    assert overall["idf1"] >= base["overall"]["idf1"] - 0.02


def test_new_tracker_beats_greedy_where_it_should():
    seeds = GATE_SEEDS[:4]
    for sc in ("crossing", "dim", "flicker", "dropout_fp"):
        new = evaluate(lambda: ByteTracker(min_hits=3), sc, seeds)
        old = evaluate(lambda: IouTracker(min_hits=3), sc, seeds)
        assert new.id_switches < old.id_switches, sc
        assert new.hota > old.hota, sc
