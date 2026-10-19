"""Synthetic generator + metrics. Everything here is SYNTHETIC; no real-world claim."""
import itertools

from tablesight.perception import iou
from tablesight.synth import SCENARIOS, generate, score_tracking
from tablesight.synth.scene import FP_PID, MERGED_PID


def _sig(sc):
    return [(f.idx, [(d.pid, d.det.box, d.det.conf, d.det.feat) for d in f.dets],
             [(g.pid, g.box) for g in f.gt]) for f in sc.frames]


def test_generator_is_deterministic_per_seed():
    for name in SCENARIOS:
        assert _sig(generate(name, 7)) == _sig(generate(name, 7))
    assert _sig(generate("busy_night", 1)) != _sig(generate("busy_night", 2))


def test_scenes_are_labelled_synthetic():
    assert generate("crossing", 0).synthetic is True


def test_ground_truth_has_roles_and_both_kinds():
    sc = generate("crossing", 0)
    assert {g.role for f in sc.frames for g in f.gt} == {"staff", "guest"}


def test_features_are_valid_colours():
    sc = generate("busy_night", 3)
    for f in sc.frames:
        for d in f.dets:
            assert d.det.feat is not None and all(0 <= v <= 1 for v in d.det.feat)
            assert 0 <= d.det.conf <= 1


def test_crossing_paths_really_overlap():
    sc = generate("crossing", 0)
    best = 0.0
    for f in sc.frames:
        for a, b in itertools.combinations(f.gt, 2):
            best = max(best, iou(a.box, b.box))
    assert best > 0.1


def test_staff_occlude_guests_with_dropout():
    sc = generate("staff_occludes_guest", 0)
    occluded = [g for f in sc.frames for g in f.gt if g.occlusion > 0.3]
    assert any(g.role == "guest" for g in occluded)
    # occluded guests are detected less often than unoccluded ones
    det_rate = {}
    for f in sc.frames:
        seen = {d.pid for d in f.dets}
        for g in f.gt:
            k = g.occlusion > 0.3
            n, h = det_rate.get(k, (0, 0))
            det_rate[k] = (n + 1, h + (g.pid in seen))
    assert det_rate[True][1] / det_rate[True][0] < det_rate[False][1] / det_rate[False][0]


def test_couple_produces_merged_detections():
    sc = generate("couple", 0)
    assert any(d.pid == MERGED_PID for f in sc.frames for d in f.dets)


def test_false_positives_and_dropouts_present():
    sc = generate("dropout_fp", 0)
    assert any(d.pid == FP_PID for f in sc.frames for d in f.dets)
    missed = sum(1 for f in sc.frames for g in f.gt if g.pid not in {d.pid for d in f.dets})
    assert missed > 20


def test_flicker_yields_low_confidence_detections():
    sc = generate("flicker", 0)
    low = [d for f in sc.frames for d in f.dets if d.pid > 0 and d.det.conf < 0.5]
    assert len(low) > 50


def test_dim_scene_is_noisier_than_normal():
    def mean_conf(sc):
        c = [d.det.conf for f in sc.frames for d in f.dets if d.pid > 0]
        return sum(c) / len(c)
    assert mean_conf(generate("dim", 0)) < mean_conf(generate("crossing", 0)) - 0.1


# ---- metrics -------------------------------------------------------------------------------
def _oracle(sc, rename=None):
    return [[((rename(f.idx, g.pid) if rename else g.pid), g.box) for g in f.gt] for f in sc.frames]


def test_oracle_tracker_scores_perfectly():
    sc = generate("crossing", 0)
    m = score_tracking(sc, _oracle(sc))
    assert m.id_switches == 0 and m.fp == 0 and m.fn == 0
    assert m.idf1 == 1.0 and abs(m.hota - 1.0) < 1e-9


def test_id_renumbering_is_counted_as_switches():
    sc = generate("crossing", 0)
    m = score_tracking(sc, _oracle(sc, rename=lambda i, pid: pid + 100 * (i // 100)))
    assert m.id_switches >= 4 and m.idf1 < 1.0 and m.assa < 1.0


def test_empty_output_has_zero_tp_and_no_crash():
    sc = generate("crossing", 0)
    m = score_tracking(sc, [[] for _ in sc.frames])
    assert m.tp == 0 and m.hota == 0.0 and m.switch_rate_per_1k == 0.0


def test_swap_between_roles_is_flagged():
    sc = generate("crossing", 0)
    roles = {p.pid: p.role for p in sc.people}
    # pid 1 (guest) and pid 3 (staff) trade track ids halfway
    sw = {1: 3, 3: 1}
    out = _oracle(sc, rename=lambda i, pid: sw.get(pid, pid) if i > 150 else pid)
    m = score_tracking(sc, out)
    assert roles[1] != roles[3] and m.role_crossing_switches >= 1
