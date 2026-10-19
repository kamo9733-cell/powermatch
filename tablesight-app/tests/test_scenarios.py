import pytest

from tablesight.alerts import AlertEngine
from tablesight.simulator import run, seated_party, walk_by, with_gaps
from tablesight.table import Event, Observation, Table
from tablesight.templates import get_template


def play(tpl, spec, duration, **kw):
    tb = Table("T1", tpl)
    for o in run(spec, duration, **kw):
        tb.step(o)
    return tb


def kinds(tb):
    return [e.kind for e in tb.events]


def test_walk_by_creates_no_visit():
    tb = play(get_template("casual_dining"), walk_by(10), 200)
    assert kinds(tb) == []


def test_neglected_table_alerts_once_after_greet_window():
    tpl = get_template("casual_dining")
    tb = play(tpl, seated_party(10, 2000), 1000)
    alerts = [e for e in tb.events if e.kind == "needs_attention"]
    assert len(alerts) == 1
    assert alerts[0].detail["first_visit"] is True
    assert 10 + tpl.greet_alert_s <= alerts[0].t <= 10 + tpl.greet_alert_s + tpl.seat_confirm_s + 2


def test_staff_visit_resets_clock_and_prevents_alert():
    tpl = get_template("casual_dining")
    tb = play(tpl, seated_party(0, 2000, staff_visits=((60, 80), (400, 420))), 800)
    assert "staff_visit" in kinds(tb)
    assert "needs_attention" not in kinds(tb)


def test_restroom_gap_is_not_a_vacate():
    tpl = get_template("casual_dining")
    spec = with_gaps(seated_party(0, 2000), ((300, 300 + tpl.absence_grace_s - 20),))
    tb = play(tpl, spec, 700)
    assert "vacated" not in kinds(tb)
    assert kinds(tb).count("seated") == 1


def test_real_departure_emits_vacated_with_dwell():
    tb = play(get_template("casual_dining"), seated_party(0, 600), 1200)
    vac = [e for e in tb.events if e.kind == "vacated"]
    assert len(vac) == 1 and 590 <= vac[0].detail["dwell"] <= 620


def test_dirty_table_flagged_after_vacate():
    tpl = get_template("casual_dining")
    tb = play(tpl, seated_party(0, 300), 1500)
    assert "needs_clean" in kinds(tb)


@pytest.mark.parametrize("venue", ["cafe", "quick_service", "food_court"])
def test_no_table_service_means_no_neglect_alerts(venue):
    tb = play(get_template(venue), seated_party(0, 5000), 4000)
    assert "needs_attention" not in kinds(tb)


def test_fine_dining_is_more_patient_than_casual():
    spec = seated_party(0, 5000)
    casual = play(get_template("casual_dining"), spec, 3000)
    fine = play(get_template("fine_dining"), spec, 3000)
    first = lambda tb: next(e.t for e in tb.events if e.kind == "needs_attention")
    assert first(fine) > first(casual)


def test_stale_camera_never_triggers_alerts_or_state_changes():
    tpl = get_template("casual_dining")
    tb = play(tpl, seated_party(0, 5000), 3000, stale=True)
    assert set(kinds(tb)) == {"uncertain"} and len(tb.events) == 1


def test_low_confidence_is_explicitly_uncertain():
    tb = Table("T1", get_template("casual_dining"))
    tb.step(Observation(0, 2, 0, confidence=0.2))
    assert tb.events[-1].kind == "uncertain"


def test_rush_alerts_are_batched_into_digest_not_lost():
    tpl = get_template("casual_dining")
    eng = AlertEngine(tpl)
    tables = [Table(f"T{i}", tpl) for i in range(3)]
    for o in run(seated_party(0, 9000), 1000):
        for tb in tables:
            tb.step(o)
    evs = sorted((e for tb in tables for e in tb.events if e.kind == "needs_attention"),
                 key=lambda e: e.t)
    first = [a for e in evs if (a := eng.process(e))]
    assert len(first) == 1 and len(first[0]["tables"]) == 1
    digest = eng.flush(evs[0].t + eng.min_gap_s + 1)
    assert digest and digest["digest"] and len(digest["tables"]) == 2


def test_held_alert_discarded_if_staff_arrives():
    tpl = get_template("casual_dining")
    eng = AlertEngine(tpl)
    mk = lambda t, k, tb, **d: Event(t, tb, k, d)
    eng.process(mk(100, "needs_attention", "A", waited=200, first_visit=True))
    eng.process(mk(110, "needs_attention", "B", waited=200, first_visit=True))
    eng.process(mk(120, "staff_visit", "B"))
    assert eng.flush(300) is None


def test_single_frame_false_detection_does_not_inflate_party():
    tpl = get_template("casual_dining")
    spec = lambda t: (6 if t == 100 else 2, 0)
    tb = play(tpl, spec, 300)
    assert tb.party_size == 2


def stale_obs(tb, t0, t1, guests=2, staff=0):
    for t in range(t0, t1):
        tb.step(Observation(float(t), guests, staff, stale=True))


def test_camera_outage_time_does_not_count_as_neglect():
    tpl = get_template("casual_dining")
    tb = Table("T1", tpl)
    for t in range(40):
        tb.step(Observation(float(t), 2, 0))
    stale_obs(tb, 40, 590)                       # ~9 min blind, longer than greet_alert_s
    tb.step(Observation(590.0, 2, 0))
    assert "needs_attention" not in kinds(tb)
    assert "uncertain_end" in kinds(tb)
    for t in range(591, 590 + int(tpl.greet_alert_s) + 5):  # now real unattended time accrues again
        tb.step(Observation(float(t), 2, 0))
    assert "needs_attention" in kinds(tb)


def test_outage_does_not_fabricate_staff_visit():
    tpl = get_template("casual_dining")
    tb = Table("T1", tpl)
    for t in range(41):
        tb.step(Observation(float(t), 2, 1 if t >= 38 else 0))   # staff arrives just before the outage
    stale_obs(tb, 41, 200)
    tb.step(Observation(200.0, 2, 1))
    assert kinds(tb).count("staff_visit") == 0


def test_second_outage_is_recorded_too():
    tb = Table("T1", get_template("casual_dining"))
    for t in range(40):
        tb.step(Observation(float(t), 2, 0))
    stale_obs(tb, 40, 41)
    tb.step(Observation(41.0, 2, 0))
    stale_obs(tb, 42, 43)
    assert kinds(tb).count("uncertain") == 2 and kinds(tb).count("uncertain_end") == 1


def test_alert_cap_resets_each_visit_and_backwards_clock_does_not_wedge():
    tpl = get_template("casual_dining")
    eng = AlertEngine(tpl)
    sent = 0
    for visit in range(tpl.max_alerts_per_table + 2):
        base = visit * 10_000
        eng.process(Event(base, "A", "seated"))
        sent += bool(eng.process(Event(base + 200, "A", "needs_attention", {"waited": 200, "first_visit": True})))
        eng.process(Event(base + 900, "A", "vacated"))
    assert sent == tpl.max_alerts_per_table + 2
    eng2 = AlertEngine(tpl)
    eng2.process(Event(50_000, "A", "needs_attention", {"waited": 200, "first_visit": True}))
    assert eng2.process(Event(100, "B", "needs_attention", {"waited": 200, "first_visit": True}))  # clock jumped back
