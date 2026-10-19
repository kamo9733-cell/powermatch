"""SQLite schema (Postgres-portable SQL). Every tenant-owned table carries org_id."""
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS orgs(id TEXT PRIMARY KEY, name TEXT, plan TEXT DEFAULT 'trial',
  created_at REAL);
CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY, email TEXT UNIQUE, pw TEXT,
  verified INTEGER DEFAULT 0, totp_secret TEXT, failed INTEGER DEFAULT 0, locked_until REAL DEFAULT 0,
  lang TEXT DEFAULT 'en');
CREATE TABLE IF NOT EXISTS memberships(user_id TEXT, org_id TEXT, role TEXT, location_id TEXT,
  section TEXT, PRIMARY KEY(user_id, org_id));
CREATE TABLE IF NOT EXISTS sessions(token_hash TEXT PRIMARY KEY, user_id TEXT, org_id TEXT,
  expires REAL);
CREATE TABLE IF NOT EXISTS tokens(token_hash TEXT PRIMARY KEY, purpose TEXT, user_id TEXT, expires REAL);
CREATE TABLE IF NOT EXISTS invites(token_hash TEXT PRIMARY KEY, org_id TEXT, email TEXT, role TEXT,
  location_id TEXT, expires REAL);
CREATE TABLE IF NOT EXISTS locations(id TEXT PRIMARY KEY, org_id TEXT, name TEXT, venue_type TEXT,
  tz TEXT DEFAULT 'UTC', staff_analytics TEXT DEFAULT 'anonymized', retention_days INTEGER DEFAULT 30,
  cloud_video INTEGER DEFAULT 0, lang TEXT DEFAULT 'en', currency TEXT DEFAULT 'USD');
CREATE TABLE IF NOT EXISTS cameras(id TEXT PRIMARY KEY, org_id TEXT, location_id TEXT, name TEXT,
  url_enc BLOB, angle_score REAL);
CREATE TABLE IF NOT EXISTS devices(id TEXT PRIMARY KEY, org_id TEXT, location_id TEXT, token_hash TEXT,
  last_seen REAL, version TEXT, health TEXT);
CREATE TABLE IF NOT EXISTS pairing(code_hash TEXT PRIMARY KEY, org_id TEXT, location_id TEXT, expires REAL);
CREATE TABLE IF NOT EXISTS events(org_id TEXT, location_id TEXT, event_id TEXT, t REAL, table_id TEXT,
  kind TEXT, detail TEXT, PRIMARY KEY(org_id, event_id));
CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY AUTOINCREMENT, org_id TEXT, user_id TEXT,
  action TEXT, target TEXT, t REAL);
CREATE TABLE IF NOT EXISTS webhooks(id TEXT PRIMARY KEY, org_id TEXT, url TEXT, secret TEXT);
CREATE TABLE IF NOT EXISTS corrections(id INTEGER PRIMARY KEY AUTOINCREMENT, org_id TEXT, location_id TEXT,
  kind TEXT, payload TEXT, consent_training INTEGER DEFAULT 0, t REAL);
CREATE INDEX IF NOT EXISTS ev_loc ON events(org_id, location_id, t);
"""


def connect(path: str = ":memory:") -> sqlite3.Connection:
    c = sqlite3.connect(path, check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.executescript(SCHEMA)
    return c
