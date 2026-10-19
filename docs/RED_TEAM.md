# Red team (ranked)
1. **Alert suppression drops, not batches.** During a rush, tables flagged inside `min_gap_s` are lost forever. Fix: queue and emit a digest. (Test `test_alert_cap_per_table_and_rush_spacing` currently asserts the lossy behaviour.)
2. Staff/guest role errors are not modelled yet; one misclassified server in a table zone silences a real neglect alert.
3. Party size uses a running max, so a one-frame false detection inflates it.
4. `needs_clean` fires on any vacated table with no clean signal source — needs POS/staff-wipe evidence or it will over-alert.
5. Midnight / DST: sim time is plain seconds; business-day bucketing not built.
6. Bag/coat table-holding, mirrors, street people: no perception yet, no tests.
