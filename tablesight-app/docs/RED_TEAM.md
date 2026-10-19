# Red team (ranked)
1. ~~Alert suppression drops, not batches.~~ FIXED (digest via `AlertEngine.flush`, tests added). During a rush, tables flagged inside `min_gap_s` are lost forever. Fix: queue and emit a digest. (Test `test_alert_cap_per_table_and_rush_spacing` currently asserts the lossy behaviour.)
2. Staff/guest role errors are not modelled yet; one misclassified server in a table zone silences a real neglect alert.
3. ~~Party size inflated by one-frame detections.~~ FIXED (needs 5 consecutive agreeing ticks).
4. `needs_clean` fires on any vacated table with no clean signal source — needs POS/staff-wipe evidence or it will over-alert.
5. Midnight / DST: sim time is plain seconds; business-day bucketing not built.
6. Bag/coat table-holding, mirrors, street people: no perception yet, no tests.
7. **Single shared SQLite connection** across FastAPI worker threads is not safe under real concurrency; needs a pool/Postgres before multi-user load.
8. Login rate limit and account lock are in-process/per-email: a distributed attacker or multi-node deploy defeats the limiter; lock can be abused to deny a victim login (accepted trade-off, needs per-IP + captcha-free backoff).
9. Email verification tokens/invites are returned via the Outbox interface only; no real delivery path, so signup is unusable in production until a notifier exists.
10. Session fixation is limited (random tokens, hashed at rest) but there is no session revocation UI and no CSRF story yet (bearer tokens only; revisit if cookies are introduced).
11. `needs_attention` timers run on observation time; a manager's clock drift on the edge could shift alerts — server should timestamp-check batches.

## From the independent code review (unfixed / partially fixed)
12. **Alerting stack not wired:** `AlertEngine`, `Escalator`/`AlertRouter` and `notify.adaptive` overlap; `Table` still uses fixed thresholds; `staff_visit` events carry no `staff` field so staff-level reports are empty; `reports` ignore `uncertain`/`needs_clean`. (Fixed: ack payload now has table + time.)
13. `shift_report(window=...)` drops visits whose `seated` precedes the window (turn median biased short); `seated_t` is the confirm time while dwell starts at true seat time.
14. `Homography.apply` has no guard for pixels above the horizon (w<=0) => wrong floor positions.
15. `login` picks the first membership; there is no org switching.
16. Existing SQLite files keep the old events primary key (org_id,event_id); new DBs use (org_id,location_id,event_id).
17. Demo mode is detected client-side from the location name, and `seed_demo` fakes device heartbeats (so staleness can't appear organically in the demo).
Fixed this pass (with regression tests in tests/test_review_fixes.py and tests/test_scenarios.py): skewed-clock data loss on the edge, false alerts/visits after a camera outage, oldest-first event listing, per-table alert cap never resetting, backwards clock wedging the alert gap, digest closing for all tables, lookalike-localhost pairing, NaN forecasts, flusher overflow, section never stamped on events, retention not enforced.
18. **Foot-point anchoring fails for seated guests on oblique cameras** (seen in the first real clip, a wall-mounted wide-angle view of a Korean-BBQ restaurant): seated people's feet are hidden under tables/benches and their boxes are partly occluded by other guests and grills, so `foot_point` (box bottom-centre) can land on the wrong table or the floor beyond it. Needs a seat-aware anchor (hip/box-centre for sitting poses) or per-camera zone polygons drawn in image space; not built, not tested on real data.
19. Real clip also shows: a burned-in timestamp/brand overlay, heavy compression, people only ~1/10 frame height at the far end, tabletop grills with steam, and an app UI over the video (it is a phone screen recording, not a raw RTSP stream) — none of which the synthetic scenes cover.
