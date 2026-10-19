"""Score zone occupancy on a real clip against hand labels (smoke test, NOT a benchmark: one clip, one scene)."""
import argparse
import json
from pathlib import Path

from tablesight.geometry import Zone, assign_zone, assign_zone_by_overlap, foot_point

ap = argparse.ArgumentParser()
ap.add_argument("dets")
ap.add_argument("--zones", default="evalset/rec-001/zones.json")
ap.add_argument("--labels", default="evalset/rec-001/labels.json")
ap.add_argument("--min-conf", type=float, default=0.35)
a = ap.parse_args()
zones = [Zone(z["id"], [tuple(p) for p in z["poly"]], z["kind"]) for z in json.loads(Path(a.zones).read_text())["zones"]]
lab = json.loads(Path(a.labels).read_text())
rows = [json.loads(line) for line in Path(a.dets).read_text().splitlines()]


def score(assign):
    occ_ok = occ_n = cnt_ok = cnt_n = 0
    for r in rows:
        counts = {z.zone_id: 0 for z in zones}
        for x1, y1, x2, y2, c in r["dets"]:
            if c < a.min_conf:
                continue
            z = assign((x1, y1, x2, y2))
            if z:
                counts[z.zone_id] += 1
        for k, want in lab["occupied"].items():
            occ_ok += (counts[k] > 0) == want
            occ_n += 1
        for k, want in lab["count"].items():
            cnt_ok += counts[k] == want
            cnt_n += 1
    return occ_ok / occ_n, cnt_ok / cnt_n, occ_n


for name, fn in [("foot_point rule", lambda b: assign_zone(foot_point(b), zones)),
                 ("box-overlap rule", lambda b: assign_zone_by_overlap(b, zones))]:
    o, c, n = score(fn)
    print(f"{name:18s} occupancy acc {o:.2f}  exact-count acc (A,B) {c:.2f}  ({len(rows)} frames, {n} zone-frames)")
