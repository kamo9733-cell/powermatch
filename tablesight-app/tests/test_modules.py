import pytest

from tablesight.analytics import business_day, forecast_covers, greet_times, percentile, turn_stats
from tablesight.evaluation import id_switches, score_alerts
from tablesight.fusion import Detection, fuse
from tablesight.geometry import Homography, Zone, assign_zone, foot_point, point_in_polygon
from tablesight.health import CameraHealth, FrameStats
from tablesight.perception import IouTracker, RawDet
from tablesight.roles import UniformClassifier
from tablesight.table import Event

SQ = [(0, 0), (2, 0), (2, 2), (0, 2)]


def test_point_in_polygon():
    assert point_in_polygon((1, 1), SQ) and not point_in_polygon((3, 1), SQ)


def test_homography_maps_corners_and_centre():
    h = Homography.from_points([(0, 0), (100, 0), (100, 100), (0, 100)], [(0, 0), (4, 0), (4, 4), (0, 4)])
    assert h.apply((50, 50)) == pytest.approx((2, 2))
    persp = Homography.from_points([(10, 10), (90, 20), (100, 100), (0, 100)], [(0, 0), (4, 0), (4, 3), (0, 3)])
    assert persp.apply((90, 20)) == pytest.approx((4, 0))


def test_collinear_calibration_rejected():
    with pytest.raises(ValueError):
        Homography.from_points([(0, 0), (1, 1), (2, 2), (3, 3)], [(0, 0), (1, 0), (1, 1), (0, 1)])


def test_foot_point_uses_bottom_centre():
    assert foot_point((10, 0, 30, 100)) == (20, 100)


def test_exclusion_zone_beats_table_zone():
    zones = [Zone("t1", SQ), Zone("window", [(1, 0), (3, 0), (3, 2), (1, 2)], "exclude")]
    assert assign_zone((1.5, 1), zones) is None      # behind glass
    assert assign_zone((0.5, 1), zones).zone_id == "t1"


def test_fusion_merges_across_cameras_not_within():
    d = [Detection("A", (1, 1), .9), Detection("B", (1.2, 1), .8),
         Detection("A", (1.3, 1), .7)]               # couple seen by A: stays 2 people
    out = fuse(d)
    assert len(out) == 2


def test_tracker_keeps_id_through_short_occlusion():
    tr = IouTracker(min_hits=2, max_age=10)
    ids = set()
    for i in range(30):
        dets = [] if 10 <= i < 14 else [RawDet((i, 0, i + 40, 100), .9)]
        ids |= {t for t, _ in tr.update(dets)}
    assert len(ids) == 1


def test_tracker_separates_two_people():
    tr = IouTracker(min_hits=2)
    for _ in range(5):
        out = tr.update([RawDet((0, 0, 40, 100), .9), RawDet((200, 0, 240, 100), .9)])
    assert len({t for t, _ in out}) == 2


def test_untrained_venue_returns_unknown_not_guess():
    assert UniformClassifier().classify((0.6, 0.5, 0.5)) == ("unknown", 0.0)


def test_corrections_teach_classifier_and_black_on_black_is_uncertain():
    c = UniformClassifier()
    for _ in range(3):
        c.correct((0.6, 0.8, 0.5), "staff")        # blue shirts
    c.correct((0.1, 0.8, 0.9), "guest")
    assert c.classify((0.6, 0.8, 0.52))[0] == "staff"
    assert c.classify((0.1, 0.8, 0.9))[0] == "guest"
    c2 = UniformClassifier()
    for _ in range(3):
        c2.correct((0.0, 0.0, 0.05), "staff")      # black uniform
    c2.correct((0.0, 0.0, 0.06), "guest")          # guest also in black
    assert c2.classify((0.0, 0.0, 0.055))[0] == "unknown"


def test_health_detects_frozen_dark_and_bump():
    h = CameraHealth(frozen_after_s=5)
    sig = tuple(float(i) for i in range(16))
    for t in range(8):
        iss = h.update(FrameStats(t, 100, 50, sig))
    assert "frozen" in iss
    assert "covered_or_dark" in CameraHealth().update(FrameStats(0, 3, 50, sig))
    h2 = CameraHealth()
    h2.update(FrameStats(0, 100, 50, sig))
    moved = tuple(v + 100 for v in sig)
    assert "moved_or_bumped" in h2.update(FrameStats(1, 100, 50, moved))


def test_score_alerts_precision_recall_delay():
    s = score_alerts([("A", 100), ("B", 500)], [("A", 90), ("C", 300)])
    assert s.precision == 0.5 and s.recall == 0.5 and s.median_delay_s == 10


def test_id_switches():
    assert id_switches([{1: 7}, {1: 7}, {2: 7}]) == 1


def test_analytics():
    evs = [Event(0, "A", "seated"), Event(100, "A", "staff_visit"),
           Event(900, "A", "vacated", {"dwell": 900})]
    assert greet_times(evs) == [100]
    assert turn_stats(evs)["reliable"] is False
    assert percentile([1, 2, 3, 4], .5) == 2.5
    assert forecast_covers({12: [40, 50]}, 12)["covers"] is None
    assert forecast_covers({12: [40, 50, 60]}, 12)["covers"] == 50
    assert business_day(1.0, 100) == 99 and business_day(12, 100) == 100
