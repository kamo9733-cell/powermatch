# First real-footage results (rec-001) — SMOKE TEST, NOT A BENCHMARK
**What:** YOLOX-S (opencv_zoo ONNX, person class, 3 overlapping tiles for small distant people) on an 11 s wall-camera clip, 42 frames (every 15th). Zones and counts below were hand-labelled by the lead from the same clip, so this is **not independent** and one scene only.

| Assignment rule | Occupancy accuracy (5 tables) | Exact guest count (tables A, B) |
|---|---|---|
| foot point (box bottom-centre) | 1.00 | **0.05** |
| box-overlap (new, `assign_zone_by_overlap`) | 1.00 | **0.90** |
(min detection confidence 0.35; at 0.5: 0.15 vs 0.88.) Reproduce: `python scripts/clip_detect.py data/rec-001.mov --out data/ev --every 15 --tiles 3 --conf 0.3 && python scripts/real_clip_eval.py data/ev/dets.jsonl` (needs the git-ignored clip and `models/yolox_s_2022nov.onnx`).

**What it shows**
- The foot-point rule from the original design is wrong on this camera: seated guests' box bottoms land past their table. Counting by box overlap with image-space table zones fixes it on this clip. (`tests/test_real_clip.py` guards this locally.)
- Tiling matters: one 640px pass on the 2622px-wide frame finds 6-8 people, 3 tiles find 10-11 (same clip). Far-table people are tiny and produce overlapping duplicate boxes; far table C was only scored for occupancy.
- Seated vs standing cannot be told from box aspect on this oblique view (measured ratios 0.42-0.65 for both), so the planned "aspect ratio => seated" idea is rejected.

**What it does NOT show:** role classification (no uniforms identifiable, aisle people unlabelled), tracking, neglect alerts, other cameras/lighting/venues, any generalisation. Detector weights: COCO-trained; training-data licence unverified (DECISIONS D7).
