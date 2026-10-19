# Tracker evaluation baseline (SYNTHETIC data only)

**Every number below comes from synthetic scenes produced by `tablesight/synth/scene.py`
(seeded, numpy). They are not real footage and say nothing about real-world accuracy.** They
rank two trackers on the same simulated detector failures; absolute values will differ on real
cameras. Reproduce: `python -m tablesight.synth` (about 8 s).

## Setup
- 7 scenarios x 10 fixed seeds (0-9), 300 frames each at 10 fps, 1280x720, about 94k ground-truth
  boxes in total. Scenarios and their failure models: `docs/SYNTHETIC_DATA.md`.
- Trackers (same `update(list[RawDet]) -> list[(id, box)]` interface, `min_hits=3`):
  `IouTracker` (old greedy IoU, unchanged) vs `ByteTracker` (new: two-stage high/low confidence
  association, constant-velocity alpha-beta prediction, Hungarian assignment, torso-colour cue).
- Metrics (`tablesight/synth/metrics.py`): per-frame optimal matching at IoU >= 0.5, ID switches via
  `tablesight.evaluation.id_switches`, switch rate per 1000 matched GT boxes, IDF1-lite (one global
  id<->person assignment), HOTA-lite = sqrt(DetA x AssA) at a single IoU threshold. These are
  simplified: not TrackEval, not comparable to MOT leaderboards. "Role-crossing" counts a track id
  jumping to a person of the other role (staff<->guest), the switch that matters most for the hero loop.

## Results (measured)
| scenario | tracker | ID sw. | sw./1k | role-crossing sw. | IDF1-lite | HOTA-lite | DetA | AssA |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| crossing | greedy IoU | 29 | 4.7 | 6 | 0.678 | 0.721 | 0.895 | 0.588 |
| crossing | ByteTrack-style | 4 | 0.6 | 2 | 0.947 | 0.900 | 0.900 | 0.901 |
| staff_occludes_guest | greedy IoU | 0 | 0.0 | 0 | 0.968 | 0.939 | 0.939 | 0.939 |
| staff_occludes_guest | ByteTrack-style | 0 | 0.0 | 0 | 0.969 | 0.939 | 0.939 | 0.940 |
| couple | greedy IoU | 1116 | 137.7 | 36 | 0.473 | 0.480 | 0.690 | 0.339 |
| couple | ByteTrack-style | 1189 | 144.7 | 51 | 0.607 | 0.572 | 0.700 | 0.478 |
| dim | greedy IoU | 61 | 11.2 | 17 | 0.542 | 0.561 | 0.784 | 0.405 |
| dim | ByteTrack-style | 29 | 5.3 | 16 | 0.774 | 0.713 | 0.781 | 0.660 |
| dropout_fp | greedy IoU | 257 | 26.9 | 35 | 0.382 | 0.401 | 0.475 | 0.347 |
| dropout_fp | ByteTrack-style | 145 | 14.8 | 23 | 0.506 | 0.496 | 0.508 | 0.490 |
| flicker | greedy IoU | 115 | 10.1 | 20 | 0.709 | 0.702 | 0.853 | 0.584 |
| flicker | ByteTrack-style | 68 | 5.9 | 27 | 0.755 | 0.733 | 0.857 | 0.634 |
| busy_night | greedy IoU | 1188 | 63.5 | 263 | 0.318 | 0.326 | 0.537 | 0.199 |
| busy_night | ByteTrack-style | 851 | 45.6 | 287 | 0.389 | 0.378 | 0.554 | 0.259 |
| **ALL** | greedy IoU | 2766 | 39.1 | 377 | 0.581 | 0.590 | | |
| **ALL** | ByteTrack-style | 2286 | 32.2 | 406 | 0.707 | 0.676 | | |

Headline (synthetic): total ID switches 2766 -> 2286 (-17%); switch rate 39.1 -> 32.2 per 1k;
IDF1-lite 0.581 -> 0.707; HOTA-lite 0.590 -> 0.676. Excluding the two scenarios dominated by
merged detections (couple, busy_night), switches fall 462 -> 246 (10.5 -> 5.6 per 1k).

## Where the new tracker still fails (do not oversell)
1. **Couples standing/walking close (merged detections): not fixed, slightly worse on switches**
   (1116 -> 1189; role-crossing 36 -> 51). When the detector fuses two people into one box,
   association cannot recover identities; the better prediction just hops between the two. IDF1/HOTA
   improve there (0.47 -> 0.61), but ~145 switches per 1k boxes is unusable. Needs a detector that
   separates close people (or a crowd-aware head), not a better tracker.
2. **Staff<->guest identity swaps are not reduced overall** (377 -> 406, driven by couple and
   busy_night). A staff/guest swap would corrupt role smoothing in `FloorPipeline`; role voting per
   track should be reset or down-weighted after a high-ambiguity association (not built).
3. **Busy night (everything at once) is still poor**: 45.6 switches/1k, HOTA-lite 0.378. Dropouts,
   false positives and merges compound.
4. **Persistent false positives** (static "poster/mirror" ghosts, conf 0.55-0.8) become confirmed
   tracks in both trackers (see `fp` counts in `baseline.json`); only exclusion zones stop them.
5. **Staff occluding guests** is already fine for both trackers (0 switches); the cost shows up as
   missed detections (DetA 0.94), not identity errors. `max_age` is 30 frames, enough for the
   10-20 frame occlusions simulated; longer ones are untested.
6. Parameters were checked for sensitivity on separate seeds (100-111): alpha/beta/IoU/max_age/
   min_hits/appearance variants moved total switches by under about 15%, so the gap above is not a
   tuning artefact, but nothing is tuned for real cameras either.

## CI gate
`tests/test_tracker.py` re-runs ByteTracker on the 7 x 10 gate set and fails if, per scenario or
overall, switches/1k exceeds `baseline * 1.10 + 0.25`, or HOTA-lite/IDF1-lite drop by more than
0.02 (`tablesight/synth/baseline.json`). It also asserts the new tracker beats greedy IoU on
crossing, dim, flicker and dropout_fp. If you improve the tracker, re-record with
`python -m tablesight.synth --write-baseline`, review the diff and update the table above.
Seeds use numpy's PCG64; a numpy release that changes streams would need a deliberate re-baseline.
