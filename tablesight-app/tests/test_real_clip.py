"""Real-footage smoke gate. Skips unless the (git-ignored) clip and ONNX model exist locally."""
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
CLIP, MODEL = ROOT / "data" / "rec-001.mov", ROOT / "models" / "yolox_s_2022nov.onnx"
pytestmark = pytest.mark.skipif(not (CLIP.exists() and MODEL.exists()), reason="real clip/model not present (local only)")


def test_overlap_rule_beats_foot_rule_on_real_seated_guests():
    cv2 = pytest.importorskip("cv2")
    from tablesight.geometry import Zone, assign_zone, assign_zone_by_overlap, foot_point
    from tablesight.perception_yolox import YoloXPerson
    zones = [Zone(z["id"], [tuple(p) for p in z["poly"]]) for z in json.loads((ROOT / "evalset/rec-001/zones.json").read_text())["zones"]]
    cap = cv2.VideoCapture(str(CLIP))
    cap.set(cv2.CAP_PROP_POS_FRAMES, 120)
    ok, frame = cap.read()
    assert ok
    dets = YoloXPerson(str(MODEL), conf=0.35, tiles=3).detect(frame)
    def counts(assign):
        c = {z.zone_id: 0 for z in zones}
        for d in dets:
            z = assign(d.box)
            if z:
                c[z.zone_id] += 1
        return c
    ov = counts(lambda b: assign_zone_by_overlap(b, zones))
    ft = counts(lambda b: assign_zone(foot_point(b), zones))
    assert ov["A"] == 2 and ov["B"] == 2 and ov["D"] == 0 and ov["E"] == 0
    assert (ft["A"], ft["B"]) != (2, 2)   # the old rule demonstrably mis-assigns on this camera
