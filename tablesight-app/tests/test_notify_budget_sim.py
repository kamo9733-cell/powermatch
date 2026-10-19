"""A busy night must stay within the alerts/hour target from docs/QUALITY_TARGETS.md (<= 6)."""

import heapq
import random
import re
from pathlib import Path

from tablesight.escalation import AlertRouter, Escalator, Shift, ShiftSchedule, Staff
from tablesight.notify.adaptive import AlertBudget, adapt
from tablesight.templates import TEMPLATES

H = 3600.0


def target_per_hour() -> int:
    text = (Path(__file__).parent.parent / "docs" / "QUALITY_TARGETS.md").read_text()
    return int(re.search(r"<=\s*(\d+)\s+alerts/hour", text).group(1))


def run_night(seed: int, raw_per_hour: float = 60.0):
    rng = random.Random(seed)
    tpl = TEMPLATES["casual_dining"]
    sections = ["A", "B", "C"]
    staff = [Staff(f"srv{s}", f"S{s}", "server", s) for s in sections]
    staff += [Staff(f"lead{s}", f"L{s}", "section_lead", s) for s in sections]
    staff += [Staff("mgr", "M", "manager"), Staff("off", "Off", "server", "A")]
    sched = ShiftSchedule([Shift(s.id, 0, 5 * H) for s in staff if s.id != "off"])
    sched.add(Shift("off", 6 * H, 9 * H))  # never on shift during the night
    budget = AlertBudget(max_per_hour=target_per_hour())
    esc = Escalator(staff, sched, budget=budget)
    rush = adapt(tpl, 19, 0.9)  # a Friday-night rush: digest mode, wider spacing
    router = AlertRouter(esc, min_gap_s=rush.min_gap_s)
    tables = [(f"T{i}", sections[i % 3]) for i in range(40)]
    per_table: dict[str, int] = {}
    raw = capped = 0
    log, events = [], []  # dispatch log; heap of (t, kind, payload)
    t = 0.0
    while t < 4 * H:
        if rng.random() < raw_per_hour / H * 30:
            tb, sec = rng.choice(tables)
            if per_table.get(tb, 0) >= tpl.max_alerts_per_table:
                capped += 1
            else:
                per_table[tb] = per_table.get(tb, 0) + 1
                raw += 1
                new = router.submit(tb, sec, t, rush.mode)
                log += new
                for d in new:
                    if rng.random() < 0.7:
                        heapq.heappush(events, (t + rng.uniform(30, 100), 0, d))
        while events and events[0][0] <= t:
            _, kind, d = heapq.heappop(events)
            if kind == 1:
                router.table_resolved(d, t)  # a visit happened: the table is attended
            elif esc.ack(d.alert_id, d.staff_id, t):
                for tb in d.tables:
                    heapq.heappush(events, (t + 60, 1, tb))
        t += 30
        log += esc.tick(t)
        log += router.flush(t)
    return raw, capped, log, router, esc


def rolling_max(log, who_filter):
    by: dict[str, list[float]] = {}
    for d in log:
        if who_filter(d):
            by.setdefault(d.staff_id, []).append(d.t)
    worst = 0
    for times in by.values():
        for i, end in enumerate(times):
            worst = max(worst, sum(1 for x in times[: i + 1] if x > end - H))
    return worst


def test_busy_night_stays_under_alerts_per_hour_target():
    cap = target_per_hour()
    assert cap == 6
    for seed in range(5):
        raw, _, log, router, esc = run_night(seed)
        assert raw > 60  # the night really was busy (>15 raw neglect events / hour)
        assert rolling_max(log, lambda d: d.role == "manager") <= cap
        assert rolling_max(log, lambda d: True) <= cap  # every recipient, not just managers
        assert router.stats["digests"] > 0 and any(d.role == "manager" for d in log)
        # digests merged several tables into each ping instead of one ping per table
        assert router.stats["merged"] > router.stats["digests"]
        assert all(d.staff_id != "off" for d in log)  # never alert off-shift staff
        assert all(esc.schedule.on_shift(d.staff_id, d.t) for d in log)


def test_budget_actually_binds_without_it_the_same_night_exceeds_target():
    # sanity: the simulation is not trivially under the cap
    import tablesight.notify.adaptive as ad

    orig = ad.AlertBudget.allow
    ad.AlertBudget.allow = lambda self, who, t: True
    try:
        _, _, log, _, _ = run_night(0)
    finally:
        ad.AlertBudget.allow = orig
    assert rolling_max(log, lambda d: True) > target_per_hour()
