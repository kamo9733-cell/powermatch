"""Proxy metrics on a detections file when no ground truth exists: stability, duplicates, track fragmentation."""
import json
import statistics as st
import sys
from pathlib import Path

from tablesight.perception import ByteTracker, IouTracker, RawDet, iou

rows = [json.loads(s) for s in Path(sys.argv[1]).read_text().splitlines()]
conf = float(sys.argv[2]) if len(sys.argv) > 2 else 0.35


def dets(r):
    return [RawDet((a, b, c, d), s) for a, b, c, d, s in r["dets"] if s >= conf]


counts = [len(dets(r)) for r in rows]
jump = [abs(counts[i] - counts[i - 1]) for i in range(1, len(counts))]


def inside(a, b):
    """a mostly inside b (or vice versa): the classic duplicate-on-one-person pattern."""
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    small = min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1]))
    return small > 0 and inter / small > 0.8


dup_frames = []
for r in rows:
    ds = dets(r)
    dup_frames.append(sum(1 for i in range(len(ds)) for j in range(i + 1, len(ds))
                          if iou(ds[i].box, ds[j].box) > 0.5 or inside(ds[i].box, ds[j].box)))
print(f"frames={len(rows)} people/frame mean={st.mean(counts):.1f} sd={st.pstdev(counts):.1f} "
      f"mean |delta| between sampled frames={st.mean(jump):.2f}")
print(f"probable duplicate pairs/frame mean={st.mean(dup_frames):.1f} (box pairs IoU>0.5 or >80% contained)")
for name, tr in (("greedy IoU", IouTracker(min_hits=3)), ("ByteTracker", ByteTracker())):
    ids, life = set(), {}
    for r in rows:
        for tid, _ in tr.update(dets(r)):
            ids.add(tid)
            life[tid] = life.get(tid, 0) + 1
    frag = len(ids) / max(1.0, st.mean(counts))
    print(f"{name:12s} distinct track ids={len(ids)}  ids per average-visible-person={frag:.1f}  "
          f"median track length={st.median(life.values()):.0f} frames  (1.0 would be perfect for a static crowd)")
