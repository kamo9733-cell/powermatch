# Analytics design (CLAUDE.md 4.4, 4.6, 4.7)

Pure, dependency-free modules: `tablesight/reports.py`, `forecast.py`, `queueing.py`, `capacity.py`.
Tests: `tests/test_reports.py`, `test_forecast.py`, `test_queueing.py`, `test_capacity.py`.
Every function documents its assumptions in its docstring; this page summarises the design and the
measured behaviour. Numbers below were produced by running the code (synthetic data, fixed seeds).

## Principles

- Medians and percentiles, never bare averages. Every summary carries `n`, `reliable` (n >= 5)
  and `p90_reliable` (n >= 10). Min/max are included so readers see a range.
- Refuse rather than guess: forecasts, comparisons, wait estimates, remaining-time estimates and
  RevPASH return an explicit "no estimate" with a reason when data is insufficient.
- Team-level framing. No ranking of people; staff-level output is off by default, suppressed under
  5 samples, alphabetical, and always carries a caveat. The "systemic vs individual" check can
  answer `systemic: load-related`, `systemic: widespread`, `undetermined` or `insufficient data`.
  It has no "individual" verdict by design.
- Like with like: comparisons use the same weekday and (optionally) daypart, prior days only,
  with holiday exclusion, a thin-day filter and a minimum of 3 comparable days.
- Time: durations are real epoch differences (DST-safe). Calendar logic (business day, weekday,
  daypart) uses local wall-clock via `zoneinfo` and the existing `analytics.business_day`
  semantics: 01:00 Saturday belongs to Friday. On a fall-back night both 01:30 occurrences map
  to the same business day; the day is 25 hours long for RevPASH (tested). Dayparts run on a
  business clock (after midnight = 24+), so `late` is 22:00 to 05:00.

## Shift report (`reports.shift_report`)

Inputs are the state machine's events plus optional alert and ack lists. Output: turn median/p90,
greet distribution (seat to first staff visit, buckets <2m, 2-5m, 5-10m, >=10m), check-back gaps,
walk-aways (`walk_away` events, emitted by a host/queue module), alerts detected/sent/acknowledged,
excluded sensor artefacts (dwell <= 0 or > 6 h), and the framing block. Known limitation: greet
time is measured from the `seated` event, which is stamped after seat confirmation, so it
understates true greet time by that lag. An acknowledgement is credited to one alert only.
`compare_like_with_like` reports the target day against the median and range of comparable days
and calls a difference only when outside that range widened by 10 percent of the reference.

## Forecasting (`forecast.py`)

Two methods, both with 80 percent prediction intervals and refusal below 3 comparable days.

- `seasonal_naive`: median of the same weekday and hour over the last 8 weeks. Interval is median
  plus or minus z x robust sigma x sqrt(1 + 1/n), with a Poisson floor (sqrt of the median).
- `ewma_ratio`: seasonal baseline x exponentially weighted ratio of how recent days ran against
  their own baseline (alpha 0.4, clamped to 0.5..2.0). Interval combines baseline and ratio
  spread. One-step-ahead only.

Backtest: rolling origin over the last 40 days of 150 synthetic days (400 hour-points per run,
nothing tuned on test days). WAPE = sum of absolute errors / sum of actuals; coverage is the share
of actuals inside the nominal 80 percent interval.

| scenario | seed | seasonal-naive WAPE / bias / coverage | ewma-ratio WAPE / bias / coverage |
|---|---|---|---|
| stable | 1 | 0.178 / -0.19 / 0.83 | 0.188 / +0.20 / 0.84 |
| stable | 2 | 0.180 / -0.97 / 0.78 | 0.183 / -0.10 / 0.80 |
| stable | 3 | 0.177 / -0.27 / 0.79 | 0.187 / +0.15 / 0.80 |
| 5% disruption days | 1 | 0.254 / +1.21 / 0.73 | 0.279 / -0.26 / 0.69 |
| 5% disruption days | 2 | 0.178 / -0.56 / 0.82 | 0.185 / -0.07 / 0.81 |
| 5% disruption days | 3 | 0.176 / -0.15 / 0.81 | 0.180 / -0.18 / 0.81 |
| +5%/week trend | 1 | 0.163 / -5.63 / 0.73 | 0.143 / +0.17 / 0.83 |
| +5%/week trend | 2 | 0.176 / -6.27 / 0.67 | 0.157 / +0.38 / 0.81 |
| +5%/week trend | 3 | 0.163 / -6.16 / 0.70 | 0.137 / -0.26 / 0.82 |

Honest reading: with a stable level, ewma-ratio is not better (slightly worse, 0.183 to 0.188
against 0.177 to 0.180); with a trend it removes the bias (about -6 covers per hour for
seasonal-naive) and improves WAPE by roughly 0.02 and coverage from about 0.70 to about 0.82.
Disruption days hurt both and ewma-ratio can be worse right after one (seed 1). The generator is far more regular than a real venue;
expect real errors to be larger and re-run the backtest on each venue's own history before
showing a number to an owner. With only 40 days of history, days 28 to 39 are forecast
with no refusals (WAPE 0.180, coverage 0.84); on day index 3 all 10 hourly points are refused.

## Table-ready predictions

`DwellModel` keeps empirical completed-visit dwell per party bucket (1-2, 3-4, 5+).
`remaining(party, elapsed)` conditions on dwell > elapsed (survival style) and reports the
median with a 20th to 80th percentile range; it pools all parties when a bucket has fewer than 8
conditional samples and refuses when the party has outlasted every sample. Example on synthetic
dwell (200 two-top visits, mean 55 min): a two-top seated 10 min ago is estimated at 46 min left
(range 36 to 55); at 40 min, 17 min (9 to 25); at 70 min, 6 min (2 to 10, thin sample).
`quote_wait` takes the (ahead+1)-th soonest eligible table and says so; it ignores table
combining. Completed-visit samples bias slightly short (visits in progress are unseen).

## Queueing (`queueing.py`)

`estimate_wait` = queue length / recent departure rate (Little's law, W = L / lambda).
Sanity checks: no estimate when the queue is stalled (no departures in the window) or fewer
than 3 departures; capped at 2 h and flagged; flagged `inconsistent` when it disagrees with
recently observed waits by more than 2x. Example: 6 people waiting, 15 served in the last 10 min
(one per 40 s) gives 224 s. `littles_law_check` verifies L = lambda W on logged visits and refuses
under 10 arrivals; use it to decide whether to trust the queue data at all. `queue_alerts`
(`long_queue`, `long_wait`, `stalled`) needs the condition to persist, clears with hysteresis,
has cooldowns, and ignores uncertain samples.

## Capacity (`capacity.py`)

Licensed capacity 100 gives enter thresholds near 90, at 100, over 101 and exit thresholds near
85, at 95, over 96 (5 percent hysteresis). A higher state must be held 30 s without interruption;
a lower state needs 120 s below the exit threshold. Consequence: a count bouncing 99/101 is not
confirmed as over (no alert spam) at the cost of delayed detection; a sustained breach is caught
(both tested). Stale, negative and implausible (>3x licence) samples are skipped and counted;
count plus uncertainty above the licence is surfaced as `possible_breach`. This is an aid, not
the legal head count.

## Section balance

Load = (open covers + 2 x tables flagged needing attention) / servers. `suggest_seating` ranks
staffed sections that have a fitting empty table, calls the floor balanced below a 3-cover gap,
and ignores unstaffed sections (with a note). `rebalance_hint` suggests extra coverage for a
heavy section using team-level wording.

## Revenue per available seat-hour

`PosEvent` (t, check_id, amount, kind payment or refund, table) is the whole POS interface;
no integration exists. `net_revenue` de-duplicates retransmitted (check_id, kind) pairs and
rejects negative, non-finite and unknown-kind events. `rev_per_seat_hour` divides by seats x real
elapsed hours less closed seat-hours and refuses below 0.5 available seat-hours. Revenue is
attributed by payment time, so use windows of at least a daypart. `occupied_seat_hours` gives
guest-hours seated, a lower-bound utilisation numerator.

## Open items

- Alert acknowledgement and `walk_away` events are not yet emitted by the existing pipeline;
  the report accepts them via the documented shapes.
- Forecast intervals need a real-data calibration pass; holiday calendars feed `exclude`.
- No heatmaps or multi-location benchmarking here (ROADMAP items 26 and others).
