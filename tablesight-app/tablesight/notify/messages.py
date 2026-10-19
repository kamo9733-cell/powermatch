"""Alert copy. Coaching tone: invite, don't accuse; describe the table, not the person.

Avoided on purpose: surveillance/blame wording ("monitoring", "tracked", "caught", "ignored",
"late", "failed", "violation", "idle", "neglect"), staff names in escalations, and urgency
theatre. Keys use the project's i18n key style; see docs/ALERTING_DESIGN.md for the list to merge
into tablesight/i18n/catalogs/*.json (the loader there only reads en/ar/de/es/fr.json, so a new
catalog file would never be picked up; until merged, `render` falls back to the English below).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .base import Message

if TYPE_CHECKING:
    from ..escalation import Dispatch

EN: dict[str, str] = {
    "notify.nudge.title": "Table {table} might like a check-in",
    "notify.nudge.body": "Seated {minutes} min, no visit yet. A quick hello goes a long way.",
    "notify.digest.title": "{n} tables could use a hello",
    "notify.digest.body": "Tables: {tables}. Grab whichever is closest.",
    "notify.lead.title": "Section {section} could use a hand",
    "notify.lead.body": "{what} Could you help cover?",
    "notify.manager.title": "Floor support needed in {section}",
    "notify.manager.body": "{what} The section team may be busy right now.",
    "notify.what.one": "Table {table} has been waiting about {minutes} min.",
    "notify.what.many": "{n} tables are waiting: {tables}.",
    "notify.action.ack": "On it",
    "notify.action.snooze": "Give me 10 minutes",
    "notify.resolved": "All set, thanks!",
}

BANNED = (
    "monitor", "track", "caught", "ignored", "late", "fail", "violation", "idle", "neglect",
    "slack", "warning", "blame", "surveil", "watching",
)  # fmt: skip


def render(key: str, **kw) -> str:
    return EN[key].format(**kw)


def build_message(d: Dispatch, minutes: int = 0) -> Message:
    n = len(d.tables)
    tables = ", ".join(d.tables)
    if d.level == 0:
        if n == 1:
            title = render("notify.nudge.title", table=tables)
            body = render("notify.nudge.body", minutes=minutes)
        else:
            title = render("notify.digest.title", n=n)
            body = render("notify.digest.body", tables=tables)
        prio = "normal"
    else:
        what = (
            render("notify.what.one", table=tables, minutes=minutes)
            if n == 1
            else render("notify.what.many", n=n, tables=tables)
        )
        key = "notify.lead" if d.level == 1 else "notify.manager"
        title = render(f"{key}.title", section=d.section)
        body = render(f"{key}.body", what=what, section=d.section)
        prio = "normal" if d.level == 1 else "high"
    return Message(d.alert_id, d.staff_id, title, body, prio, tuple(d.tables))
