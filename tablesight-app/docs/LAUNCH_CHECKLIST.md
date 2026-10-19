# Launch checklist (status after the multi-agent pass + review fixes)
## Done and tested (synthetic/unit level)
- [x] Tenant isolation tests; 49 adversarial security tests (docs/SECURITY_REVIEW.md)
- [x] Auth: scrypt, email verify, reset, lockout, per-IP/email rate limits, TOTP 2FA, hashed tokens, session list/revoke
- [x] RBAC without escalation; camera credentials encrypted (Fernet); TLS via bundled Caddy
- [x] Idempotent edge replay, outage buffering, dead-letter for rejected events, clock-skew correction hook
- [x] Honest-state rules: stale/low-confidence => "uncertain" + recovery event; outage time never counts as neglect
- [x] Retention purge job (hourly, per-location setting) with tests
- [x] Edge: ONVIF probe/parse, motion-gated FPS, Ed25519 update verification, pairing, hardened installer script (dry-run tested)
- [x] Manager web UI (manager/host/TV/settings), 18 browser tests, WCAG contrast checks
- [x] Alerting: escalation, shift filtering, ack state machine, signed webhook / ntfy / SMTP / chat transports
- [x] Analytics: shift reports (team-level), forecasts with backtests, queue, capacity, table-ready
## Not done — blockers before real customers
- [ ] **Real perception model**, chosen by benchmarking on licensed/consented footage (docs/DATA.md). No real-footage metric exists.
- [ ] Camera pipeline wired into the edge service (capture -> detector -> FloorPipeline -> outbox); `edge/__main__` only sends heartbeats today
- [ ] Alerting stack unified: AlertEngine (alerts.py) vs Escalator/AlertRouter (escalation.py) overlap; Table does not use adaptive thresholds; ack -> report wiring
- [ ] Update download/staged install/rollback; real NVR integration (only ONVIF probe parsing exists)
- [ ] Postgres + migrations (SQLite is single node; events PK changed this pass, no migration for old DBs)
- [ ] Real email/SMS/push senders in production config (interfaces + transports only)
- [ ] Not implemented but referenced in the legal drafts (marked [NOT YET IMPLEMENTED]): blurring, video-access audit, encryption at rest of DB/backups, minor handling
- [ ] Passwordless/social sign-in, org switching (login picks the first membership), webhooks endpoints
- [ ] Production serving of `web/` (Caddy route added; needs real TLS domain and CSP review)
- [ ] Counsel review of everything in docs/legal/; human security review; load test; restore drill
- [ ] Server-side demo flag (UI currently detects "DEMO MODE" in the location name)
