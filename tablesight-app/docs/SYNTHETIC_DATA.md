# Synthetic data and labelling tools

**All generated data is synthetic.** It exercises tracker and role logic against modelled detector
failures. It is not footage, contains no real people, and must never be quoted as real-world accuracy.

## Generator (`tablesight/synth/scene.py`)
`generate(scenario, seed)` returns a `Scene` (always `synthetic=True`): per frame the noisy detector
output (`RawDet` box, confidence, torso HSV colour; no faces) plus exact ground truth (person id,
role, box, occlusion fraction). Same scenario and seed give identical output (tested). Pure
python + numpy.

| scenario | what is modelled |
|---|---|
| `crossing` | 2 guests + 2 staff on X-shaped paths that overlap (IoU > 0.1) |
| `staff_occludes_guest` | staff walk in front of standing guests; detection probability falls with occlusion, box noise rises |
| `couple` | pairs walking/standing close; boxes fuse into one merged detection (30% of frames) |
| `dim` | candlelight: lower confidence, 2.5x box jitter, 3x colour noise, desaturated colour, more misses |
| `dropout_fp` | per-person dropout bursts of 3-12 frames, transient false positives, 2 static "poster" ghosts |
| `flicker` | 30% of detections collapse to confidence 0.15-0.45 |
| `busy_night` | 10 wanderers + dim + dropouts + FPs + flicker + merges |

Limits: boxes are drawn from a crude perspective model, motion is piecewise linear, noise is
Gaussian and independent per frame (real detectors are correlated), roles use a colour prior only,
no mirrors/glass, no children, no camera motion. Real clips will be harder in ways not modelled here.

## Metrics and benchmark
`tablesight/synth/metrics.py` (ID switches, IDF1-lite, HOTA-lite) and `tablesight/synth/benchmark.py`
(`python -m tablesight.synth`). Results and the CI gate: `docs/EVAL_BASELINE.md`.

## Labelling tool (`python -m tablesight.labeling`)
JSONL, one record per line, schema v1 (`tablesight/labeling/schema.py`).
- `clip`: camera, `tracks` (pid, role staff|guest|unknown, box per frame, occluded flag), tags,
  and a `lineage` block: source (synthetic | public_dataset | internal_capture | customer),
  source_ref, licence, collected_at, `covert_capture`, `contains_minors`, `faces_blurred`, and
  `consent` {obtained, scope [eval, training], recorded_at, evidence_ref}.
- `correction`: imported manager tap (role | table_empty | wrong_alert) with `consent.training`.

Validator rules: licence must be on the reviewed commercial-OK list (non-commercial or unknown is an
error); covert capture is always an error; customer/internal footage needs recorded consent; the
`training` scope needs consent evidence and a timestamp and is never allowed with minors; boxes must
be valid, in-frame, frames strictly increasing. Training eligibility defaults to off.

```
python -m tablesight.labeling new --out clips.jsonl --clip-id c1 --source customer \
    --licence customer-consent-agreement --venue-id loc1      # skeleton; fails validate until consent filled in
python -m tablesight.labeling new --out clips.jsonl --append --clip-id s1 --from-synth crossing --seed 3
python -m tablesight.labeling validate clips.jsonl             # exit 1 on any error
python -m tablesight.labeling summarise clips.jsonl            # counts, licences, training-eligible
python -m tablesight.labeling import-corrections --input corrections_export.json --out clips.jsonl
```
Correction import reads rows shaped like the platform `corrections` table (JSON array or JSONL),
pseudonymises `org_id` (sha256 prefix), keeps `consent_training` as exported (default 0), rejects
malformed rows with a reason and skips duplicates, so re-running is safe.

Not built: an interactive annotation UI (this is the schema, validators and CLI the UI would write
to) and packaging: `pyproject.toml` still lists only `packages = ["tablesight"]`, so the new
subpackages (`synth`, `labeling`) are not included in an installed wheel until that is updated.
