#!/bin/sh
# Online-safe SQLite backup + restore test. Usage: backup.sh /data/tablesight.db /backups
set -eu
db="$1"; dir="$2"; ts=$(date -u +%Y%m%dT%H%M%SZ)
mkdir -p "$dir"
python3 - "$db" "$dir/ts-$ts.db" <<'PY'
import sqlite3, sys
src, dst = sqlite3.connect(sys.argv[1]), sqlite3.connect(sys.argv[2])
src.backup(dst); dst.close()
chk = sqlite3.connect(sys.argv[2]).execute("PRAGMA integrity_check").fetchone()[0]
assert chk == "ok", chk
print("backup verified:", sys.argv[2])
PY
