"""Role-classifier probe on a local clip (needs git-ignored data/rec-003.mov + data/ev003_t3/dets.jsonl).
Trains UniformClassifier on the waiter (staff) and a few guests in frame 0, then labels every box; writes an annotated frame."""

import colorsys
import json
from pathlib import Path

import cv2

from tablesight.roles import UniformClassifier

VID = "data/rec-003.mov"
rows = [json.loads(s) for s in Path("data/ev003_t3/dets.jsonl").read_text().splitlines()]
cap = cv2.VideoCapture(VID)


def torso(fr, b):
    x1, y1, x2, y2 = [int(v) for v in b]
    h = y2 - y1
    w = x2 - x1
    c = fr[
        max(0, y1 + int(0.22 * h)) : max(1, y1 + int(0.55 * h)),
        x1 + int(0.2 * w) : max(x1 + int(0.2 * w) + 1, x1 + int(0.8 * w)),
    ]
    if c.size == 0:
        return None
    m = c.reshape(-1, 3).mean(0)[::-1] / 255  # RGB 0..1
    return colorsys.rgb_to_hsv(*m)


feats = {}
for r in rows:
    cap.set(cv2.CAP_PROP_POS_FRAMES, r["frame"])
    ok, fr = cap.read()
    if not ok:
        continue
    feats[r["frame"]] = [(d[:4], d[4], torso(fr, d[:4])) for d in r["dets"] if d[4] >= 0.35]
# train: waiter = largest box in frame 0 (staff x3 from frames 0,5,10), guests = 3 smallest-index others in frame 0 right side
clf = UniformClassifier()
for f in (0, 5, 10):
    big = max(feats[f], key=lambda t: (t[0][2] - t[0][0]) * (t[0][3] - t[0][1]))
    clf.correct(big[2], "staff")
guests = [t for t in feats[0] if t[0][0] > 1500][:4]
for t in guests:
    clf.correct(t[2], "guest")
tot = staff = unk = 0
per = {}
for f, L in feats.items():
    for b, s, hsv in L:
        if hsv is None:
            continue
        r, c = clf.classify(hsv)
        tot += 1
        staff += r == "staff"
        unk += r == "unknown"
print("boxes", tot, "staff", staff, "unknown", unk, "guest", tot - staff - unk)
# annotate one later frame
f = sorted(feats)[len(feats) // 2]
cap.set(cv2.CAP_PROP_POS_FRAMES, f)
ok, fr = cap.read()
for b, s, hsv in feats[f]:
    r, c = clf.classify(hsv)
    col = {"staff": (0, 0, 255), "guest": (0, 255, 0), "unknown": (0, 200, 255)}[r]
    x1, y1, x2, y2 = [int(v) for v in b]
    cv2.rectangle(fr, (x1, y1), (x2, y2), col, 4)
    cv2.putText(fr, r[:1].upper(), (x1, y1 + 30), cv2.FONT_HERSHEY_SIMPLEX, 1.6, col, 4)
cv2.imwrite("data/roles003.jpg", cv2.resize(fr[:, 240:2380], None, fx=0.46, fy=0.46))
print("frame", f)
