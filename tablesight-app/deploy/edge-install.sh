#!/bin/sh
# One-command edge install (draft). Owner runs: sh edge-install.sh <PAIRING_CODE> <API_URL>
set -eu
code="${1:?pairing code from the dashboard}"; api="${2:?https://your-tablesight-host}"
python3 -m venv /opt/tablesight-edge && /opt/tablesight-edge/bin/pip install tablesight
echo "pairing with $api ..."
# TODO(edge-runtime): exchange code via POST $api/edge/pair, store token 0600, install systemd unit.
echo "paired (stub). See docs/help/edge-install.md"
