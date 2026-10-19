# Model card (current honest status)
**No perception model ships yet.** A provisional YOLOX-S person detector (adapter `perception_yolox.py`, weights not shippable until licence-verified) has been run on one real clip: see docs/EVAL_REAL.md (smoke test, hand-labelled by the author, one scene). The detector is a pluggable interface (`tablesight/perception.py`); the bundled `IouTracker` is a dependency-free baseline, and `UniformClassifier` is a colour-prototype staff/guest heuristic trained only from manager corrections.

## What is measured
Only **synthetic** results (simulator + `tests/test_hero_loop.py`): on scripted scenes, neglect-alert precision/recall >= 0.9 and delay within 60 s of the template threshold. These prove the reasoning layer, **not real-world accuracy**. No real-footage number exists; do not quote one.

## Known weaknesses / where accuracy will drop (unmeasured, expected)
- Black-on-black uniforms: classifier returns "unknown" and lowers confidence rather than guessing.
- Occlusion by staff/pillars, dim candlelight, IR mode, steam: untested without footage.
- Mirrors/windows: handled only by manual exclusion zones.
- Staff in plain clothes, delivery drivers, owners seated with friends: no handling yet.
- Tracker is greedy-IoU: ID switches on crossing paths likely; `id_switches` metric exists, no real clips.

## Intended use
Coaching nudges to managers; never automated discipline of individuals. Not for biometric identification.


## Real-footage status (updated)
Evaluated (smoke-level, author-eyeballed, 3 clips) in docs/EVAL_REAL.md. Summary: person detection + zone assignment OK on a static CCTV view; tracking fragments on busy/moving scenes; **staff-vs-guest classification failed** (0/3 visible staff correct on a checked frame). Not ready for any customer-facing alert that depends on knowing who is staff.
