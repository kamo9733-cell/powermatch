# Licences (draft)
| Component | Licence | Where | Obligations |
|---|---|---|---|
| Python stdlib / own code | n/a / proprietary | core | — |
| pytest, ruff (dev only) | MIT | CI | none shipped |
| RF-DETR Nano–Large (candidate) | Apache-2.0 | perception | NOTICE, attribution; check weights |
| ByteTrack (candidate) | MIT | tracking | notice |
| MediaMTX / go2rtc (candidates) | MIT | streaming | notice |
Rejected: Ultralytics YOLO (AGPL-3.0), RF-DETR XL/2XL (PML 1.0).
| FastAPI, Pydantic, Uvicorn, Starlette | MIT / MIT / BSD-3 / BSD-3 | platform | notices (verify from installed LICENSE files via scripts/gen_notices.py) |
| cryptography | Apache-2.0 OR BSD-3 | credential vault, update signatures | notice; licence not yet re-checked from LICENSE file |
| Caddy (deploy) | Apache-2.0 | TLS reverse proxy | notice |
| opencv-python (optional, edge) | Apache-2.0 | RTSP capture | **wheels bundle FFmpeg (LGPL, possibly GPL builds) — not inspected; review before shipping** (docs/EDGE_RUNTIME.md) |
| ntfy (protocol client only, no code vendored) | Apache-2.0 / GPLv2 dual | notify/ntfy.py | rely on Apache-2.0 |
| Playwright (dev/test only) | Apache-2.0 | UI tests | none shipped |
