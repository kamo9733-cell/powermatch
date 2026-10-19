# Failure catalogue → mitigation → test (CLAUDE.md §5.3)
Status: **T** = tested on synthetic data, **P** = partial, **O** = open (needs perception/footage).
| Failure | Mitigation | Status | Test |
|---|---|---|---|
| Same person seen by 2 cameras | geometry fusion, cross-camera only | T | test_fusion_merges_across_cameras_not_within |
| Couple merged / split | same-camera detections never merged | P | same test; detector-level merge is O |
| Track ID switch / occlusion | IoU tracker max_age coasting | P | test_tracker_keeps_id_through_short_occlusion; crossing paths O |
| Mirrors/windows/street | exclusion zones win over table zones | T | test_exclusion_zone_beats_table_zone, test_people_in_window_exclusion_zone... |
| Staff vs guest, black-on-black | classifier returns unknown, confidence lowered | T | test_corrections_teach_classifier_and_black_on_black_is_uncertain |
| Untrained venue | no guessing before 3 corrections | T | test_untrained_venue_makes_no_confident_alerts |
| Walk-bys | min seat confirm time | T | test_walk_by_creates_no_visit |
| Restroom / smoking gap | absence grace | T | test_restroom_gap_is_not_a_vacate |
| Busser vs server, runner, manager touch | none (single "staff" role) | O | — |
| Shift-meal staff at table | none | O | — |
| Bags/coats holding table | none | O | — |
| Tables merged/split, layouts | layout presets planned | O | — |
| Children/minors | no individual analytics policy (legal) | P | policy only (docs/legal) |
| Dim/IR/steam/glare | not testable without footage | O | — |
| Camera frozen/covered/bumped | CameraHealth + stale => uncertain | T | test_health_detects_frozen_dark_and_bump, test_stale_camera_freezes_logic |
| Network outage / replay / dupes | durable outbox + idempotent ingest | T | test_outage_buffering_and_replay_end_to_end |
| Rush alert spam | per-table cap + digest | T | test_rush_alerts_are_batched_into_digest_not_lost |
| Venue open past midnight | business_day helper | P | test_analytics (helper only; not wired in) |
| DST / time zones | UTC storage, tz conversion helper | P | test_rtl_and_fallback_and_tz |
| Clock drift on edge | none | O | — |
| Cross-tenant data leak | org_id from session only; 404 on foreign ids | T | test_tenant_isolation_across_every_resource |
