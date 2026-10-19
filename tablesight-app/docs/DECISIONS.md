# Decisions

## D1. Reasoning core first, in Python (core modules are stdlib-only; platform needs FastAPI/cryptography, synthetic eval needs numpy — see pyproject extras)
- **Question:** what to build first given no licensed restaurant footage exists yet?
- **Evidence:** CLAUDE.md §0.3/§5.1 — most real-world reliability comes from the reasoning layer, which is testable via simulator without video.
- **Choice:** `tablesight/` pure-Python state machine + alert policy + scenario simulator; perception plugs in later behind an interface.
- **Revisit if:** the edge agent needs a different language for footprint reasons.

## D2. Detector shortlist (code licences read from each repo's LICENSE file on 2026-10-19; weights NOT yet checked)
| Candidate | Code licence | Notes |
|---|---|---|
| RF-DETR (Nano–Large) | Apache-2.0 (LICENSE verified) | XL/2XL weights are under Roboflow PML 1.0 — **excluded**. Docs say core models Apache-2.0; verify each weight file before shipping. |
| RT-DETR (lyuwenyu) | Apache-2.0 (verified) | Weights licence still to verify per checkpoint. |
| YOLOX | Apache-2.0 (verified) | Older, mature; COCO weights provenance to check. |
| Ultralytics YOLO | AGPL-3.0 | **Rejected**: network-copyleft conflicts with closed-source SaaS. |
- **Status:** provisional. Final pick requires benchmarking on our eval clips (not yet possible: no clips). Detector stays a pluggable interface.

## D3. Tracking / streaming
- ByteTrack (MIT), MediaMTX (MIT), go2rtc (MIT) verified from LICENSE. Candidates, not yet benchmarked.
- Appearance re-ID across cameras is **deferred** pending the biometric-law review (GDPR/BIPA/CUBI); use geometry-based fusion by default.

## D4. Alert policy
- Per-table cap and per-recipient spacing. Suppressed alerts are held and sent as one digest; held alerts are discarded if staff arrives first.

## D5. Platform stack (2026-10-19)
- **Choice:** FastAPI (MIT) + Pydantic (MIT) + SQLite now (SQL kept Postgres-portable) + Caddy (Apache-2.0) for TLS; stdlib scrypt/HMAC for auth, `cryptography` (Apache-2.0/BSD) for Fernet. All permissive, all self-hostable, zero cloud calls.
- **Why SQLite first:** fastest vertical slice with tenant-isolation tests; single-node limit is recorded in LAUNCH_CHECKLIST.
- **Revisit when:** more than one API node, or write contention at rush; move to Postgres (PostgreSQL licence) with row-level security as defence in depth.
- **Tenancy rule:** org_id comes only from the session/device token; unknown and foreign ids both return 404.

## D6. Cross-camera fusion is geometry-only
Floor-plan distance between detections from different cameras; no appearance re-ID (privacy: docs/legal/PRIVACY_ANALYSIS.md).
