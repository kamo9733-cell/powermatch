"""Retention enforcement: delete events (and ack/correction rows) older than each location's setting."""


def purge(db, now: float) -> dict[str, int]:
    """Returns rows deleted. Safe to run repeatedly; one transaction so a crash never half-purges."""
    with db.tx():
        ev = db.execute(
            "DELETE FROM events WHERE t < ? - 86400.0 * (SELECT retention_days FROM locations l "
            "WHERE l.id = events.location_id AND l.org_id = events.org_id)", (now,)).rowcount
        co = db.execute(
            "DELETE FROM corrections WHERE t < ? - 86400.0 * COALESCE((SELECT retention_days FROM locations l "
            "WHERE l.id = corrections.location_id AND l.org_id = corrections.org_id), 30)", (now,)).rowcount
        # orphaned events (location deleted) have no retention setting: drop them too
        orphan = db.execute("DELETE FROM events WHERE location_id NOT IN (SELECT id FROM locations)").rowcount
    return {"events": ev + orphan, "corrections": co}
