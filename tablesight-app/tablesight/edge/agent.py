"""Edge agent core: durable outbox + idempotent replay + heartbeat. Transport is injected (testable offline)."""
import json
import sqlite3
import time
import uuid
from collections.abc import Callable

Sender = Callable[[list[dict]], dict]  # raises on network failure


class Outbox:
    def __init__(self, path: str = ":memory:"):
        self.db = sqlite3.connect(path)
        self.db.execute("CREATE TABLE IF NOT EXISTS q(seq INTEGER PRIMARY KEY AUTOINCREMENT, body TEXT)")
        self.db.commit()

    def add(self, t: float, table_id: str, kind: str, detail: dict | None = None) -> str:
        eid = uuid.uuid4().hex  # assigned once at creation, so retries are deduplicated server-side
        body = json.dumps({"event_id": eid, "t": t, "table_id": table_id, "kind": kind, "detail": detail or {}})
        self.db.execute("INSERT INTO q(body) VALUES(?)", (body,))
        self.db.commit()
        return eid

    def pending(self, limit: int = 500) -> list[tuple[int, dict]]:
        return [(r[0], json.loads(r[1])) for r in self.db.execute("SELECT seq, body FROM q ORDER BY seq LIMIT ?", (limit,))]

    def ack(self, upto_seq: int) -> None:
        self.db.execute("DELETE FROM q WHERE seq<=?", (upto_seq,))
        self.db.commit()

    def __len__(self) -> int:
        return self.db.execute("SELECT COUNT(*) FROM q").fetchone()[0]


class Flusher:
    """Exponential backoff with jitter-free cap; never drops events on failure."""

    def __init__(self, outbox: Outbox, send: Sender, base_s: float = 2, cap_s: float = 300):
        self.outbox, self.send, self.base_s, self.cap_s = outbox, send, base_s, cap_s
        self.failures, self.next_try = 0, 0.0

    def tick(self, now: float | None = None) -> bool:
        now = now if now is not None else time.time()
        if now < self.next_try:
            return False
        batch = self.outbox.pending()
        if not batch:
            return True
        try:
            self.send([b for _, b in batch])
        except Exception:
            self.failures += 1
            self.next_try = now + min(self.cap_s, self.base_s * 2 ** self.failures)
            return False
        self.outbox.ack(batch[-1][0])
        self.failures, self.next_try = 0, 0.0
        return True
