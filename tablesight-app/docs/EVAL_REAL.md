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


---
# Second round: three clips, detector + tracker + role probe (SMOKE TEST, author-eyeballed, private footage)
Clips: rec-001 (CCTV, Korean BBQ, static camera), rec-002 and rec-003 (watermarked stock previews of a daylight open-air resort restaurant; rec-003 looks hand-held/panning, has the watermark across the centre and phone-player controls over part of the video). **Footage is local and git-ignored; nothing from it is published.** No ground-truth labels exist for rec-002/003, so below are proxy metrics from `scripts/clip_stats.py` and eyeballed observations from a few frames. Treat every line as indicative, not as accuracy.

## Detector (YOLOX-S, person, conf 0.35)
| Clip | Tiles | People/frame (mean) | Notes |
|---|---|---|---|
| rec-002 | 1 | 14.1 | single 640 px pass misses far people |
| rec-002 | 3 | 21.3 | more far diners found; ~1.4 probable duplicate boxes/frame |
| rec-003 | 1 | 10.3 | |
| rec-003 | 3 | 21.8 | ~2.3 probable duplicates/frame (boxes on the same person, e.g. the close-up waiter and seated couples) |
Eyeballed misses in rec-002 frame 0: a seated man in the middle (purple shirt) had **no box**; several far background people missed; duplicate boxes on the stroller group and left table. The close-up waiter in rec-003 gets two overlapping boxes. Tiling roughly doubles detections on all clips, but tile seams create duplicates.

## Tracking (sampled ~6 fps, `ids per average-visible-person`; 1.0 = perfect only for a static crowd, and these scenes are NOT static, so >1 is partly legitimate)
| Clip | greedy IoU | ByteTracker |
|---|---|---|
| rec-001 (static camera, seated) | 1.4 | 1.3 |
| rec-002 | 2.9 | 1.7 |
| rec-003 (moving view) | 4.4 | 2.4 |
ByteTracker fragments clearly less than greedy IoU on the busier clips, but still re-issues IDs well above 1 per person; do not rely on track identity for anything but short windows.

## Role (staff vs guest) probe: FAILED
`scripts/clip_roles_eval.py`: trained `UniformClassifier` on the red-and-white waiter (3 frames) plus 4 guests, then labelled every box in rec-003 (2,418 boxes: 160 staff, 544 unknown, 1,714 guest). On a mid-clip frame (hand-checked): the **same waiter** it was trained on is labelled *unknown*, a second staff member (maroon shirt) *unknown*, and a staff member in a light-blue polo with white trousers is labelled *guest*. i.e. 0 of 3 visible staff correctly labelled; ~1 in 4 guests came out "unknown".
Causes: (1) mean torso colour averages a two-tone uniform (white + maroon) into an unrepresentative mauve; (2) one training person gives no coverage of other uniform variants (this venue has at least two); (3) overlapping duplicate boxes pollute the crop.
Implication: the current role feature is not viable beyond single-colour uniforms with many corrections. Next candidates: colour *histogram* features, per-venue clustering + manager confirmation of cluster identity, and requiring >= N corrections per uniform type before the classifier may output "staff".

## What this means for the hero loop
Detection and zone assignment work well enough on a static CCTV view to get table occupancy right; tracking is usable for short windows; **role classification is the blocking weakness** — without reliable staff recognition the neglect alert cannot tell "a server visited" from "a guest walked by".
