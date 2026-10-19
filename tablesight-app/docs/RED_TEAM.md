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
