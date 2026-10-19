# Launch checklist (status as of this build)
## Done and tested
- [x] Tenant isolation tests (events, cameras, devices, exports, pairing, corrections)
- [x] Auth: scrypt, email verify, reset (kills sessions), lockout, rate limit, TOTP 2FA, hashed session tokens
- [x] RBAC with no privilege escalation; camera credentials encrypted at rest
- [x] Idempotent edge replay; outage buffering; backup script with integrity check
- [x] Honest-state rules (stale/low-confidence => uncertain, no alerts)
## Not done — blockers before real customers
- [ ] Real perception model chosen by benchmarking on eval clips (needs data, docs/DATA.md)
- [ ] Real-footage accuracy and `docs/MODEL_CARD.md` numbers
- [ ] Postgres + migrations; SQLite is single-node only
- [ ] Passwordless/social sign-in, CSP on app UI, OWASP pass by a human, pen test
- [ ] Signed edge auto-updates; real edge runtime (RTSP/ONVIF ingest) — `edge-install.sh` is a stub
- [ ] Manager mobile UI, floor-plan editor, labelling tool UI
- [ ] Push/SMS/WhatsApp notifier implementations (interface only)
- [ ] Counsel review of everything in docs/legal/ (all drafts)
- [ ] Load test (many cameras at rush), observability (metrics/tracing), tested restore drill
- [ ] Time-zone/DST/business-day handling wired end to end (helper exists)
