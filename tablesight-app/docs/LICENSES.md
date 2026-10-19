# Licences (draft)
Status legend: **verified** = read from the component's own LICENSE file or installed package metadata in this repo's environment; **unverified** = taken from search results or memory (re-check before shipping). `python scripts/gen_notices.py` regenerates notices for the runtime closure and fails CI on GPL/AGPL/SSPL/unknown licences.

| Component | Licence | Status | Where | Obligations |
|---|---|---|---|---|
| FastAPI, Starlette, Pydantic, Uvicorn, httpx, anyio, h11, click, idna | MIT / BSD-3 | verified (package metadata) | platform | include notices |
| cryptography | Apache-2.0 OR BSD-3 | verified (package metadata) | credential vault, update signatures | notice |
| numpy | BSD-3 plus bundled BSD/MIT/Zlib/CC0 | verified (package metadata) | synthetic eval (not shipped to the edge) | notice if redistributed |
| certifi (via httpx) | **MPL-2.0** (weak copyleft) | verified | platform/test transitive | used unmodified as a library; keep MPL notice, publish nothing extra unless modified |
| typing_extensions | PSF-2.0 | verified | transitive | notice |
| opencv-python (optional, edge) | Apache-2.0 | unverified | RTSP capture | **wheels bundle FFmpeg (LGPL, possibly GPL builds) — not inspected. Prefer opencv-python-headless and inspect the build before shipping** |
| Caddy image `caddy:2` (deploy) | Apache-2.0 | unverified | TLS reverse proxy | notice |
| `python:3.12-slim` base image | Debian packages incl. GPL components | unverified | container base | the image is not part of our source; document in the release notes |
| RF-DETR Nano–Large (candidate, not used yet) | Apache-2.0 code | code LICENSE verified; **weights unverified** | perception | NOTICE, check each weight file |
| RT-DETR, YOLOX, ByteTrack, MediaMTX, go2rtc (candidates) | Apache-2.0 / Apache-2.0 / MIT / MIT / MIT | LICENSE files fetched 2026-10-19 (verified for code; weights unverified) | candidates only | — |
| ntfy (protocol client only, no code vendored) | Apache-2.0 / GPLv2 dual | repo LICENSE files checked by the alerting agent | notify/ntfy.py | rely on Apache-2.0 |
| pytest, ruff, Playwright, pip-audit (dev/test only) | MIT / MIT / Apache-2.0 / Apache-2.0 | unverified | CI | none shipped |

**Rejected:** Ultralytics YOLO (AGPL-3.0); RF-DETR XL/2XL weights (Roboflow Platform Model License 1.0).
