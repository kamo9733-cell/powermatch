from datetime import UTC, datetime

from tablesight.escalation import (
    AlertRouter,
    EscalationPolicy,
    Escalator,
    Shift,
    ShiftSchedule,
    Staff,
    in_dnd,
)
from tablesight.notify.ack import DeliveryState
from tablesight.notify.adaptive import AlertBudget

H = 3600.0


def team(shifts=None, **kw):
    staff = [
        Staff("srv", "Sam", "server", "A"),
        Staff("lead", "Lee", "section_lead", "A"),
        Staff("mgr", "Max", "manager"),
    ]
    sched = ShiftSchedule(shifts or [Shift(s.id, 0, 8 * H) for s in staff])
    return Escalator(staff, sched, **kw)


def test_server_then_lead_then_manager_on_timeouts():
    e = team()
    assert [d.staff_id for d in e.start("a1", "A", 0, ("T1",))] == ["srv"]
    assert e.tick(119) == []
    assert [d.staff_id for d in e.tick(120)] == ["lead"]
    assert [d.staff_id for d in e.tick(120 + 180)] == ["mgr"]
    assert e.tick(120 + 180 + 240) == []
    assert e.status("a1") == "expired"  # chain exhausted, visibly, no loop
    assert e.tracker.get("a1:mgr").state == DeliveryState.EXPIRED


def test_ack_stops_escalation_and_is_idempotent():
    e = team()
    e.start("a1", "A", 0, ("T1",))
    assert e.ack("a1", "srv", 30)
    assert e.ack("a1", "srv", 40)  # repeat is harmless
    assert e.tick(500) == []
    assert e.tracker.get("a1:srv").state == DeliveryState.ACKED
    assert len(e.tracker.get("a1:srv").history) == 2
    assert not e.ack("a1", "mgr", 50)  # never notified


def test_start_is_idempotent():
    e = team()
    assert e.start("a1", "A", 0, ("T1",))
    assert e.start("a1", "A", 5, ("T1",)) == []


def test_resolve_cancels_pending_escalation():
    e = team()
    e.start("a1", "A", 0, ("T1",))
    assert e.resolve("a1", 60)
    assert e.tick(1000) == []
    assert e.tracker.get("a1:srv").state == DeliveryState.RESOLVED
    assert not e.ack("a1", "srv", 70)


def test_off_shift_staff_are_never_notified():
    # server's shift is over, lead starts later: alert skips straight to whoever is on shift
    shifts = [Shift("srv", 0, 100), Shift("lead", 0, 8 * H), Shift("mgr", 0, 8 * H)]
    e = team(shifts)
    assert [d.staff_id for d in e.start("a1", "A", 200, ("T1",))] == ["lead"]
    # nobody on shift at all -> nothing is sent, alert waits then expires
    e2 = team([Shift("srv", 0, 10)])
    assert e2.start("a1", "A", 500, ("T1",)) == []
    assert e2.tick(600) == []
    assert e2.tick(500 + 1800) == []
    assert e2.status("a1") == "expired"


def test_staff_coming_on_shift_picks_up_waiting_alert():
    e = team([Shift("lead", 300, 8 * H)])
    assert e.start("a1", "A", 0, ("T1",)) == []
    assert [d.staff_id for d in e.tick(300)] == ["lead"]


def test_shift_end_is_exclusive_and_bad_shift_rejected():
    s = ShiftSchedule([Shift("x", 0, 10)])
    assert s.on_shift("x", 9.9) and not s.on_shift("x", 10)
    try:
        s.add(Shift("x", 5, 5))
    except ValueError:
        return
    raise AssertionError("zero-length shift accepted")


def test_dnd_wraps_midnight_and_uses_local_tz():
    s = Staff("x", "X", "server", "A", tz="Europe/Berlin", dnd=((22 * 60, 6 * 60),))
    # 2026-01-15 22:30 UTC == 23:30 Berlin -> in DND; 12:00 UTC == 13:00 -> not
    t_night = datetime(2026, 1, 15, 22, 30, tzinfo=UTC).timestamp()
    t_day = datetime(2026, 1, 15, 12, 0, tzinfo=UTC).timestamp()
    assert in_dnd(s, t_night) and not in_dnd(s, t_day)


def test_dnd_staff_skipped():
    staff = [
        Staff("srv", "S", "server", "A", dnd=((0, 24 * 60),)),
        Staff("lead", "L", "section_lead", "A"),
    ]
    e = Escalator(staff, ShiftSchedule([Shift("srv", 0, H), Shift("lead", 0, H)]))
    assert [d.staff_id for d in e.start("a", "A", 10, ("T1",))] == ["lead"]


def test_snooze_is_capped_and_skips_person_then_returns():
    e = team()
    until = e.snooze("srv", 0, 99999)
    assert until == e.policy.max_snooze_s
    assert [d.staff_id for d in e.start("a1", "A", 10, ("T1",))] == ["lead"]
    assert [d.staff_id for d in e.start("a2", "A", until, ("T2",))] == ["srv"]


def test_snooze_defers_pending_deadline_once():
    e = team()
    e.start("a1", "A", 0, ("T1",))
    e.snooze("srv", 10, 300)
    e.snooze("srv", 20, 300)  # second snooze must not extend the same alert again
    assert e.tick(120 + 300 - 1) == []
    assert [d.staff_id for d in e.tick(120 + 300)] == ["lead"]


def test_budget_blocks_recipient_and_alert_waits():
    b = AlertBudget(max_per_hour=1)
    e = team(budget=b, policy=EscalationPolicy(max_pending_s=2 * H))
    assert [d.staff_id for d in e.start("a1", "A", 0, ("T1",))] == ["srv"]
    assert [d.staff_id for d in e.start("a2", "A", 10, ("T2",))] == ["lead"]
    assert [d.staff_id for d in e.start("a3", "A", 20, ("T3",))] == ["mgr"]
    assert e.start("a4", "A", 30, ("T4",)) == []  # everyone at budget: held, not sent
    assert [d.staff_id for d in e.tick(H + 1)] == ["srv"]


def test_router_digest_merges_and_resolves():
    e = team()
    r = AlertRouter(e, min_gap_s=90)
    assert r.submit("T1", "A", 0, "live")  # first goes live
    assert r.submit("T2", "A", 10, "live") == []  # inside the gap: held
    assert r.submit("T3", "A", 20, "digest") == []
    assert r.flush(50) == []
    out = r.flush(100)
    assert len(out) == 1 and out[0].tables == ("T2", "T3")
    r.table_resolved("T1", 110)
    assert e.status("a-A-1") == "resolved"


def test_router_off_mode_sends_nothing_and_resolved_tables_leave_digest():
    e = team()
    r = AlertRouter(e)
    assert r.submit("T1", "A", 0, "off") == []
    r.submit("T2", "A", 0, "digest")
    r.table_resolved("T2", 5)
    assert r.flush(500) == []
