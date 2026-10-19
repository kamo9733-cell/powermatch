# Progress
## Done
- Project in `tablesight-app/` (separate from the powermatch site; the GitHub token cannot create repos, 403). Branch `claude/tablesight-build`.
- Research docs (market, pricing, unit economics, roadmap) and draft legal pack — written by sub-agents from search snippets; primary-source fetches failed, so claims are tagged unverified where applicable. Treat as drafts.
- Reasoning core: state machine, templates, alert digest policy, simulator, geometry/homography, fusion, camera health, role classifier w/ corrections, IoU tracker baseline, eval metrics, analytics, hero-loop pipeline.
- Platform: tenancy, auth (2FA, lockout, reset), RBAC, plans/limits, encrypted camera creds, pairing, idempotent ingest, export, audit, data deletion, staff-analytics modes.
- Edge outbox/replay, i18n (en/ar/es/de/fr + RTL), CI workflow, Docker/Caddy/backup scripts, notices generator, marketing site with demo + ROI (browser smoke-tested at 375px), help articles.
- 53 tests green, ruff clean. All synthetic: no real-footage metrics exist (see MODEL_CARD).
## Next
1. Obtain/produce eval footage; benchmark RF-DETR/RT-DETR/YOLOX; choose detector (D2).
2. Real edge runtime (RTSP/ONVIF), Postgres migration, notifier implementations.
3. Manager mobile UI, floor editor, labelling tool.
4. Counsel review; human security review.
## Blocked
- Footage/licensed data (docs/DATA.md).
