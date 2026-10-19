# Progress
## Done
- Project in `tablesight-app/` (separate from the powermatch site; the GitHub token cannot create repos, 403). Branch `claude/tablesight-build`.
- Research docs (market, pricing, unit economics, roadmap) and draft legal pack — written by sub-agents from search snippets; primary-source fetches failed, so claims are tagged unverified where applicable. Treat as drafts.
- Reasoning core: state machine, templates, alert digest policy, simulator, geometry/homography, fusion, camera health, role classifier w/ corrections, IoU tracker baseline, eval metrics, analytics, hero-loop pipeline.
- Platform: tenancy, auth (2FA, lockout, reset), RBAC, plans/limits, encrypted camera creds, pairing, idempotent ingest, export, audit, data deletion, staff-analytics modes.
- Edge outbox/replay, i18n (en/ar/es/de/fr + RTL), CI workflow, Docker/Caddy/backup scripts, notices generator, marketing site with demo + ROI (browser smoke-tested at 375px), help articles.

- **Multi-agent pass (6 specialist agents + lead integration):** edge runtime (ONVIF probe/parse, motion-gated FPS, Ed25519 update verification, pairing, clock sync, real installer script); security hardening (21 findings fixed with tests, docs/SECURITY_REVIEW.md); alerting (escalation, shifts, ack state machine, signed webhook/ntfy/SMTP/chat notifiers, alert-budget sim); synthetic eval + ByteTracker + labelling CLI (docs/EVAL_BASELINE.md); manager web UI (manager/host/TV/settings, 18 browser tests, docs/UX_REVIEW.md); analytics (shift reports, forecasts with backtests, queueing, capacity, table-ready).
- Lead integration: GET /me and POST /alerts/ack added (needed by the UI), notify i18n keys merged into all 5 catalogs, packaging fixed, flaky UI test race fixed.
- 306 tests green (`pytest -q`, incl. 18 browser tests), ruff clean. **All accuracy numbers are synthetic**; no real-footage metrics exist (see MODEL_CARD).
- **Independent review pass (2 reviewers: code correctness, claims-vs-evidence):** ~25 findings verified; fixed: CI relocated to repo root (it could never have run) with deps/extras and browser-test enforcement, retention purge, skewed-clock data loss, outage handling in Table, newest-first events, digest resolution, site/legal overclaims (now marked [NOT YET IMPLEMENTED]), plan/site mismatch (test-locked), licence gate (regex + runtime closure + licence texts). Remaining items are listed in docs/RED_TEAM.md #12-17 and docs/LAUNCH_CHECKLIST.md.
## Next
1. Obtain/produce eval footage; benchmark RF-DETR/RT-DETR/YOLOX; choose detector (D2).
2. Wire the camera pipeline into the edge service (capture -> detector -> pipeline -> outbox); update download/rollback; Postgres migration; real SMS/push senders; floor-state API endpoint; wire notify/escalation + reports into the API.
3. Floor editor (calibration UI) and an interactive labelling UI (manager UI itself is built).
4. Counsel review; human security review.
## Blocked
- Footage/licensed data (docs/DATA.md).
