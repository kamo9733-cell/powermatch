"""Hospitality roles -> permissions. Servers see only their own section; viewers never see video."""
PERMS = {
    "owner": {"org.admin", "billing", "invite", "location.write", "camera.write", "video.view",
              "analytics.org", "analytics.location", "analytics.staff", "events.read", "export",
              "alerts.ack", "audit.read", "data.delete", "corrections.write"},
    "area_manager": {"invite", "location.write", "camera.write", "video.view", "analytics.org",
                     "analytics.location", "analytics.staff", "events.read", "export", "alerts.ack",
                     "audit.read", "corrections.write"},
    "gm": {"invite", "camera.write", "video.view", "analytics.location", "analytics.staff",
           "events.read", "export", "alerts.ack", "corrections.write"},
    "host": {"events.read", "alerts.ack", "corrections.write", "analytics.location"},
    "server": {"events.read.own_section", "alerts.ack"},
    "viewer": {"analytics.location"},
}
LOCATION_SCOPED = {"gm", "host", "server", "viewer"}
ORDER = ["viewer", "server", "host", "gm", "area_manager", "owner"]  # ascending authority


def can(role: str, perm: str) -> bool:
    return perm in PERMS.get(role, set())


def can_assign(actor_role: str, target_role: str) -> bool:
    """No privilege escalation: you can invite only roles strictly below your own."""
    return actor_role in ORDER and target_role in ORDER and ORDER.index(target_role) < ORDER.index(actor_role)


def rank(role: str) -> int:
    return ORDER.index(role) if role in ORDER else -1
