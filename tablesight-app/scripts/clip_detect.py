"""Run the YOLOX person detector over a clip and write annotated frames + detections JSONL (local only)."""
import argparse
import json
from pathlib import Path

import cv2

from tablesight.perception_yolox import YoloXPerson

ap = argparse.ArgumentParser()
ap.add_argument("clip")
ap.add_argument("--model", default="models/yolox_s_2022nov.onnx")
ap.add_argument("--out", default="data/out")
ap.add_argument("--every", type=int, default=30, help="process every Nth frame")
ap.add_argument("--tiles", type=int, default=1)
ap.add_argument("--conf", type=float, default=0.3)
a = ap.parse_args()
out = Path(a.out)
out.mkdir(parents=True, exist_ok=True)
det = YoloXPerson(a.model, conf=a.conf, tiles=a.tiles)
cap = cv2.VideoCapture(a.clip)
i = n = 0
with open(out / "dets.jsonl", "w") as f:
    while True:
        ok, fr = cap.read()
        if not ok:
            break
        if i % a.every == 0:
            ds = det.detect(fr)
            f.write(json.dumps({"frame": i, "dets": [[*d.box, d.conf] for d in ds]}) + "\n")
            for d in ds:
                x1, y1, x2, y2 = map(int, d.box)
                cv2.rectangle(fr, (x1, y1), (x2, y2), (0, 255, 0), 3)
                cv2.putText(fr, f"{d.conf:.2f}", (x1, y1 - 6), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 255, 0), 3)
            cv2.imwrite(str(out / f"f{i:04d}.jpg"), fr)
            n += 1
        i += 1
print(f"{i} frames read, {n} processed -> {out}")
