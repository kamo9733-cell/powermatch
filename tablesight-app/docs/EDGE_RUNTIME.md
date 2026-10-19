# Edge runtime

Modules in `tablesight/edge/` (all dependency-injected; tests need no camera, network or OpenCV):

| Module | Purpose |
|---|---|
| `agent.py` | Durable outbox + idempotent replay with backoff (pre-existing) |
| `source.py` | `FrameSource` protocol; `RtspSource`/`FileSource` (lazy `cv2.VideoCapture`), `ListSource` for tests |
| `onvif.py` | WS-Discovery `build_probe()` and `parse_probe_match()` (pure; UDP send to 239.255.255.250:3702 is the caller's job) |
| `motion.py` | `MotionGate` (frame differencing, no numpy) and `AdaptiveFps` (0.2 fps idle, 5 fps active, 10 s hold, geometric decay) |
| `pairing.py` | `POST /edge/pair?code=`; stores `{api, device_id, token}` atomically at 0600; refuses non-https (except localhost) and group/world-readable credential files |
| `updates.py` | Ed25519 signed manifest; rejects tampered, unsigned, wrong-key, same/lower version, missing sha256; `verify_artifact` checks the blob hash |
| `clock.py` | Midpoint (RTT-compensated) offset vs server time; `correct()` for event timestamps; `drifting()` alarm; HTTP `Date` parser |
| `health.py` | Heartbeat body (camera status ok/stale/down, fps, reconnects, outbox depth, clock offset). No URLs or credentials. |
| `__main__.py` | Heartbeat loop only. **The camera pipeline is not wired into the service yet.** |

## Known gaps
- The platform has no server-time endpoint. `ClockSync.measure` takes any callable; the intended default is the HTTP `Date` header (1 s resolution), or add `time` to the heartbeat response.
- Updates: verification exists; download, staged install, rollback and key rotation are not built. The public key must be baked into the install.
- Event `t` is not yet corrected automatically in `Outbox.add`; callers apply `ClockSync.correct()`.
- `pyproject.toml` has `packages = ["tablesight"]`, which may omit subpackages from a built wheel; the installer's `pip install` needs that checked (not my file).
- `edge-install.sh` real (non-dry) mode was not executed (it would run pip and curl). Syntax checked with dash; `--dry-run` and input validation were run.

## Licences (verify before release; versions as installed here)
- `cryptography` 50.0.1: Apache-2.0 OR BSD-3-Clause (dual); the only new runtime dependency. Verified from the package metadata/licence files at release time, not re-checked here.
- `opencv-python` / `opencv-python-headless` (optional, lazily imported): the packaging scripts are MIT and OpenCV 4.5+ is Apache-2.0. **The wheels bundle FFmpeg, which is LGPL-2.1 (dynamically linked in the wheels) and, depending on build, may include GPL/non-free codecs.** Not verified here (opencv is not installed and I did not fetch the wheel's licence files). Before shipping: inspect the wheel's `LICENSE-3RD-PARTY.txt`, keep the LGPL notice, ship it as a separately replaceable library (do not statically link), and prefer a build without `--enable-gpl`. H.264/H.265 decoding may also carry patent-pool obligations independent of copyright licence.
- Everything else is stdlib. The installer uses `curl` and `python3` (system tools, not redistributed).
- Add these to `docs/LICENSES.md` (owned elsewhere).

## Installer
`sh deploy/edge-install.sh <CODE> <API_URL> [--dry-run]` with `TS_PKG_SPEC` and `TS_PKG_SHA256` (required for a real run): hash-pinned `pip --require-hashes`, pairing exchange, 0600 credentials, hardened systemd unit (`NoNewPrivileges`, `ProtectSystem=strict`). It prints, but does not run, the root-only steps (user creation, `systemctl enable`).
