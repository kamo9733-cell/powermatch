"""Venue templates: every threshold that differs between venue types lives here."""
from dataclasses import dataclass, replace


@dataclass(frozen=True)
class VenueTemplate:
    name: str
    # Seconds a table must be continuously occupied/empty before state flips (hysteresis).
    seat_confirm_s: float
    leave_confirm_s: float
    # Seconds a table may be momentarily empty (restroom, smoking) before it counts as vacated.
    absence_grace_s: float
    # Staff presence within this window counts as "attended".
    attended_window_s: float
    # Seated-without-staff-contact threshold before the table is flagged.
    greet_alert_s: float
    # Seconds an empty-but-uncleared table may wait before a cleaning nudge (None = n/a).
    dirty_alert_s: float | None
    # Minimum staff-seconds in zone to count as a real visit (not a walk-by).
    min_visit_s: float
    # Whether table-service neglect alerts make sense at all.
    table_service: bool
    # Alert tone: how many neglect alerts per table before suppression.
    max_alerts_per_table: int


TEMPLATES: dict[str, VenueTemplate] = {
    "casual_dining": VenueTemplate("casual_dining", 20, 45, 120, 480, 180, 300, 4, True, 3),
    "fine_dining": VenueTemplate("fine_dining", 30, 60, 300, 720, 420, 300, 6, True, 2),
    "quick_service": VenueTemplate("quick_service", 15, 30, 60, 3600, 0, 180, 3, False, 1),
    "cafe": VenueTemplate("cafe", 15, 45, 300, 3600, 0, 420, 3, False, 1),
    "bar": VenueTemplate("bar", 15, 30, 120, 900, 240, 600, 3, True, 2),
    "food_court": VenueTemplate("food_court", 15, 30, 90, 3600, 0, 240, 3, False, 1),
    "patio": VenueTemplate("patio", 25, 60, 180, 600, 240, 360, 4, True, 3),
}


def get_template(name: str, **overrides) -> VenueTemplate:
    """Return a template with per-venue overrides applied."""
    return replace(TEMPLATES[name], **overrides) if overrides else TEMPLATES[name]
