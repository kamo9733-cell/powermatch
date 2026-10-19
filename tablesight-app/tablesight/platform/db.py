"""SQLite schema (Postgres-portable SQL). Every tenant-owned table carries org_id.

`connect()` returns a `LockedDB`: ONE sqlite connection shared by FastAPI's worker threads is not
safe on its own, so every statement runs under a lock and results are fully fetched before the lock
is released. `db.tx()` makes a multi-statement block atomic (and rolls back on any exception).
"""
import contextlib
import os
import sqlite3
import threading

SCHEMA = """
CREATE TABLE IF NOT EXISTS orgs(id TEXT PRIMARY KEY, name TEXT, plan TEXT DEFAULT 'trial',
  created_at REAL);
CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY, email TEXT UNIQUE, pw TEXT,
  verified INTEGER DEFAULT 0, totp_secret TEXT, failed INTEGER DEFAULT 0, locked_until REAL DEFAULT 0,
  lang TEXT DEFAULT 'en');
CREATE TABLE IF NOT EXISTS memberships(user_id TEXT, org_id TEXT, role TEXT, location_id TEXT,
  section TEXT, PRIMARY KEY(user_id, org_id));
CREATE TABLE IF NOT EXISTS sessions(token_hash TEXT PRIMARY KEY, user_id TEXT, org_id TEXT,
  expires REAL, id TEXT, created REAL, last_seen REAL, ip TEXT, ua TEXT);
CREATE TABLE IF NOT EXISTS tokens(token_hash TEXT PRIMARY KEY, purpose TEXT, user_id TEXT, expires REAL);
CREATE TABLE IF NOT EXISTS invites(token_hash TEXT PRIMARY KEY, org_id TEXT, email TEXT, role TEXT,
  location_id TEXT, expires REAL, inviter TEXT, section TEXT);
CREATE TABLE IF NOT EXISTS login_fail(email TEXT PRIMARY KEY, failed INTEGER DEFAULT 0,
  locked_until REAL DEFAULT 0);
CREATE TABLE IF NOT EXISTS locations(id TEXT PRIMARY KEY, org_id TEXT, name TEXT, venue_type TEXT,
  tz TEXT DEFAULT 'UTC', staff_analytics TEXT DEFAULT 'anonymized', retention_days INTEGER DEFAULT 30,
  cloud_video INTEGER DEFAULT 0, lang TEXT DEFAULT 'en', currency TEXT DEFAULT 'USD');
CREATE TABLE IF NOT EXISTS cameras(id TEXT PRIMARY KEY, org_id TEXT, location_id TEXT, name TEXT,
  url_enc BLOB, angle_score REAL);
CREATE TABLE IF NOT EXISTS devices(id TEXT PRIMARY KEY, org_id TEXT, location_id TEXT, token_hash TEXT,
  last_seen REAL, version TEXT, health TEXT, created REAL);
CREATE TABLE IF NOT EXISTS pairing(code_hash TEXT PRIMARY KEY, org_id TEXT, location_id TEXT, expires REAL);
CREATE INDEX IF NOT EXISTS ses_user ON sessions(user_id);
CREATE TABLE IF NOT EXISTS events(org_id TEXT, location_id TEXT, event_id TEXT, t REAL, table_id TEXT,
  kind TEXT, detail TEXT, PRIMARY KEY(org_id, event_id));
CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY AUTOINCREMENT, org_id TEXT, user_id TEXT,
  action TEXT, target TEXT, t REAL, ip TEXT);
CREATE TABLE IF NOT EXISTS webhooks(id TEXT PRIMARY KEY, org_id TEXT, url TEXT, secret TEXT);
CREATE TABLE IF NOT EXISTS corrections(id INTEGER PRIMARY KEY AUTOINCREMENT, org_id TEXT, location_id TEXT,
  kind TEXT, payload TEXT, consent_training INTEGER DEFAULT 0, t REAL);
CREATE INDEX IF NOT EXISTS ev_loc ON events(org_id, location_id, t);
"""


# Columns added after the first release: applied to pre-existing database files.
MIGRATIONS = {
    "sessions": ["id TEXT", "created REAL", "last_seen REAL", "ip TEXT", "ua TEXT"],
    "invites": ["inviter TEXT", "section TEXT"],
    "devices": ["created REAL"],
    "audit": ["ip TEXT"],
}


class Result:
    """Fully-fetched statement result (safe to use after the lock is released)."""

    def __init__(self, rows: list, rowcount: int, lastrowid: int | None):
        self.rows, self.rowcount, self.lastrowid = rows, rowcount, lastrowid

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self) -> list:
        return list(self.rows)

    def __iter__(self):
        return iter(self.rows)


class LockedDB:
    def __init__(self, conn: sqlite3.Connection):
        self._c = conn
        self._lock = threading.RLock()
        self._depth = 0

    def execute(self, sql: str, params=()) -> Result:
        with self._lock:
            cur = self._c.execute(sql, params)
            return Result(cur.fetchall(), cur.rowcount, cur.lastrowid)

    def commit(self) -> None:
        with self._lock:
            if self._depth == 0:  # inside tx() the commit happens once, at the end
                self._c.commit()

    @contextlib.contextmanager
    def tx(self):
        """Atomic block: the lock is held throughout; commit on success, rollback on any error."""
        with self._lock:
            self._depth += 1
            try:
                yield self
            except BaseException:
                self._depth -= 1
                if self._depth == 0:
                    self._c.rollback()
                raise
            else:
                self._depth -= 1
                if self._depth == 0:
                    self._c.commit()

    def close(self) -> None:
        with self._lock:
            self._c.close()


def connect(path: str = ":memory:") -> LockedDB:
    c = sqlite3.connect(path, check_same_thread=False, timeout=10)
    c.row_factory = sqlite3.Row
    c.executescript(SCHEMA)
    for table, cols in MIGRATIONS.items():
        have = {r["name"] for r in c.execute(f"PRAGMA table_info({table})")}  # identifiers come from the constant MIGRATIONS map
        for col in cols:
            if col.split()[0] not in have:
                c.execute(f"ALTER TABLE {table} ADD COLUMN {col}")  # identifiers come from the constant MIGRATIONS map
    c.commit()
    if path != ":memory:":
        c.execute("PRAGMA journal_mode=WAL")
        with contextlib.suppress(OSError):
            os.chmod(path, 0o600)  # hashes, sealed camera credentials: owner-only
    return LockedDB(c)
