# Alerting design (CLAUDE.md section 4.5)

Goal: the right person gets the right nudge at the right time, and never learns to ignore us.
Code: `tablesight/escalation.py`, `tablesight/notify/*`. Tests: `tests/test_escalation.py`, `tests/test_notify*.py`.
`alerts.py` (lead-owned, unchanged) still decides *whether* a table is flagged; this layer decides *who, how, how often*.

## 1. Escalation (`escalation.py`)
- Chain: server -> section lead -> manager. Ack timeouts 120 s / 180 s / 240 s (`EscalationPolicy`).
- Hard filters at the moment of every dispatch: on shift (`ShiftSchedule`, half-open `[start,end)`), not in the person's daily do-not-disturb window (local tz, may wrap midnight), not snoozed, under the hourly budget. There is no "critical" override: off-shift staff are never alerted.
- Snooze: capped at 15 min; it also defers a pending deadline once per alert, so snoozing cannot hold an alert hostage.
- If nobody is reachable the alert waits (retried each tick) and expires visibly after 30 min; if the manager level times out the alert expires, no loops.
- `start` and `ack` are idempotent; `resolve` (table visited/vacated) cancels pending escalation so nobody gets a stale nudge.
- `AlertRouter`: live alerts go straight out; in rush mode (or inside the spacing window, or when the budget is spent) tables are held per section and sent as one digest.

## 2. Adaptive thresholds (`notify/adaptive.py`)
`threshold = clamp(floor * daypart_mult * busy_mult, floor, 2 * floor)`, floor = template `greet_alert_s`.
Rush (occupancy >= 0.80): x1.25, digest mode, spacing x3. Quiet (< 0.35): x0.9 but never below the floor. Dayparts: lunch x1.1, dinner x1.15. Venues with `table_service=False` or `greet_alert_s=0` stay `off`. Test sweeps every template x 24 h x 21 occupancy levels (plus a per-venue override) and asserts threshold >= floor. Multipliers are starting values to validate with managers.

## 3. Ack state machine (`notify/ack.py`)
SENT -> DELIVERED -> ACKED -> RESOLVED, EXPIRED terminal. SENT may jump to ACKED (ack before receipt). Repeats, replayed event ids and backwards/late events are ignored (return False). One record per (alert, recipient). "Sent" means handed to the transport; "delivered" needs a receipt from the channel (not all channels give one).

## 4. Notifiers (`notify/`)
All take an injected transport (`HttpTransport` callable or SMTP connection factory); tests use `RecordingTransport`/fakes, no network. `urllib_transport` is the stdlib production transport (http/https only, never exercised by tests). 429/5xx/transport errors are `retryable`.
- Webhook: JSON, headers `X-Tablesight-Timestamp`, `X-Tablesight-Signature: v1=HMAC-SHA256(secret, "<ts>.<body>")`, `X-Tablesight-Delivery: alert:recipient`. `WebhookVerifier` checks constant-time signature, +/-300 s timestamp window, and rejects an already-seen signature.
- ntfy: POST `<server>/<topic>`, headers X-Title/X-Priority/X-Tags/X-Click, `Authorization: Bearer <token>` (verified against ntfy `docs/publish.md`; priority 1-5, we use 2-4, never 5). Non-ASCII titles (Arabic) go in the body because headers are not safe for them. **Licence: ntfy is dual Apache-2.0 / GPLv2** (repo root: `LICENSE` is the Apache License 2.0 text, `LICENSE.GPLv2` the other). We vendor nothing; this is an independent client of its documented HTTP API, and if code were ever copied we would rely on Apache-2.0. Self-host the server; topics act as secrets, use unguessable names. Not verified: ntfy's exact auth section (read only Bearer examples) and JSON publish field names (hence headers are used).
- SMTP: stdlib `smtplib`/`email`; stable Message-ID per alert+recipient, `Auto-Submitted: auto-generated`, address CR/LF rejected.
- Chat: Slack/Mattermost incoming-webhook body `{"username","text"}` only; plain text, `< > &` stripped (avoids mention/link injection and mrkdwn vs markdown differences).
Not built: SMS/WhatsApp (paid, third-party providers; add behind the same `Notifier` protocol) and iOS/Android push (needs ntfy app or FCM/APNs; delivery receipts there are best-effort, so ack taps are the source of truth).

## 5. Budget simulation (`tests/test_notify_budget_sim.py`)
Target parsed from `docs/QUALITY_TARGETS.md` (<= 6 alerts/hour per manager). 4 h rush, 40 tables, 3 sections, seeded random arrivals (~117 raw events after the per-table cap), 70 % acked, rest escalating. Result over 5 seeds: max rolling-hour notifications per recipient (managers and everyone else) = 6. A control run with the budget disabled exceeds 6, so the cap is what holds the line. Digests merge tables (merged > digests). Cost of the cap: a few held tables expire unsent (`stats["dropped"]`); this is surfaced, never silent.

## 6. Copy and i18n keys
Coaching tone: invite, describe the table not the person, no staff names in escalations, no surveillance/blame words (test enforces a banned-word list). Existing catalogs were not edited and `i18n.load` reads only en/ar/de/es/fr.json, so a new catalog file would never load. English strings live in `tablesight/notify/messages.py` (`EN`); **lead: merge these keys into `tablesight/i18n/catalogs/en.json` and translate**:
`notify.nudge.title`, `notify.nudge.body`, `notify.digest.title`, `notify.digest.body`, `notify.lead.title`, `notify.lead.body`, `notify.manager.title`, `notify.manager.body`, `notify.what.one`, `notify.what.many`, `notify.action.ack`, `notify.action.snooze`, `notify.resolved`.
