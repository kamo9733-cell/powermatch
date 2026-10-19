#!/bin/sh
# TableSight edge installer.  Usage: sh edge-install.sh <PAIRING_CODE> <API_URL> [--dry-run]
#   Env: TS_PKG_SPEC (pip requirement, e.g. tablesight==0.1.0)   TS_PKG_SHA256 (hash of that wheel, REQUIRED)
#        TS_PREFIX (default /opt/tablesight-edge)  TS_STATE (default /var/lib/tablesight-edge)
#        TS_UNIT_DIR (default /etc/systemd/system)
# Does: venv + hash-pinned pip install, POST /edge/pair, store token 0600, write systemd unit.
# --dry-run prints every step and changes nothing. Never uses eval; the pairing code is validated.
set -eu
umask 077

code="${1:?pairing code from the dashboard}"; api="${2:?https://your-tablesight-host}"
dry=0; [ "${3:-}" = "--dry-run" ] && dry=1
prefix="${TS_PREFIX:-/opt/tablesight-edge}"; state="${TS_STATE:-/var/lib/tablesight-edge}"
unit_dir="${TS_UNIT_DIR:-/etc/systemd/system}"
spec="${TS_PKG_SPEC:-tablesight}"; sha="${TS_PKG_SHA256:-}"

die() { echo "error: $*" >&2; exit 1; }
run() { if [ "$dry" = 1 ]; then echo "[dry-run] $*"; else "$@"; fi; }

case "$code" in ''|*[!0-9]*) die "pairing code must be digits only" ;; esac
case "$api" in https://*|http://localhost*|http://127.0.0.1*) ;; *) die "API url must be https://" ;; esac
case "$api" in *[!A-Za-z0-9:/._-]*) die "API url contains unexpected characters" ;; esac
case "$sha" in *[!0-9a-f]*) die "TS_PKG_SHA256 must be lowercase hex" ;; esac
[ "${#sha}" -eq 64 ] || [ "$dry" = 1 ] || die "set TS_PKG_SHA256 (64 hex chars) so the install is checksum-verified"
command -v python3 >/dev/null 2>&1 || die "python3 (>=3.11) required"

unit_text() {
cat <<UNIT
[Unit]
Description=TableSight edge agent
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=tablesight-edge
Environment=TABLESIGHT_STATE=$state
ExecStart=$prefix/bin/python -m tablesight.edge
Restart=always
RestartSec=5
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=yes
PrivateTmp=yes
ReadWritePaths=$state

[Install]
WantedBy=multi-user.target
UNIT
}

echo "== install package (hash-pinned) =="
run python3 -m venv "$prefix"
if [ "$dry" = 1 ]; then
  echo "[dry-run] $prefix/bin/pip install --require-hashes -r <file: $spec --hash=sha256:${sha:-<unset>}>"
else
  req="$(mktemp)"; trap 'rm -f "$req"' EXIT
  printf '%s --hash=sha256:%s\n' "$spec" "$sha" > "$req"
  "$prefix/bin/pip" install --require-hashes -r "$req"
fi

echo "== pair with $api =="
run mkdir -p "$state"
if [ "$dry" = 1 ]; then
  echo "[dry-run] POST $api/edge/pair?code=<code>  -> $state/device.json (0600)"
else
  resp="$(curl -fsS --proto '=https,http' -X POST "$api/edge/pair?code=$code")" || die "pairing refused (expired or used code?)"
  printf '%s' "$resp" | python3 -c '
import json, os, sys
api, path = sys.argv[1], sys.argv[2]
b = json.load(sys.stdin)
assert "token" in b and "device_id" in b, "bad pairing response"
fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
with os.fdopen(fd, "w") as f:
    json.dump({"api": api, "device_id": b["device_id"], "token": b["token"]}, f)
' "$api" "$state/device.json" || die "could not store credentials"
  chmod 600 "$state/device.json"
fi

echo "== systemd unit =="
if [ "$dry" = 1 ]; then unit_text; else unit_text > "$unit_dir/tablesight-edge.service"; fi
echo "Next (run as root): useradd --system tablesight-edge; chown -R tablesight-edge $state;"
echo "  systemctl daemon-reload && systemctl enable --now tablesight-edge"
