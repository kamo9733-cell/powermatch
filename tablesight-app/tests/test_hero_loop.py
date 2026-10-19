"""Synthetic end-to-end eval of the hero loop (no video). This is the CI quality gate."""
from tablesight.alerts import AlertEngine
from tablesight.evaluation import score_alerts
from tablesight.geometry import Homography, Zone
from tablesight.perception import RawDet
from tablesight.pipeline import FloorPipeline
from tablesight.roles import UniformClassifier
from tablesight.templates import get_template

BLUE, SKIN = (0.6, 0.8, 0.5), (0.08, 0.6, 0.8)
# 1 px = 1 cm; floor plan in metres
H = Homography.from_points([(0, 0), (1000, 0), (1000, 1000), (0, 1000)], [(0, 0), (10, 0), (10, 10), (0, 10)])
ZONES = [Zone("T1", [(0, 0), (3, 0), (3, 3), (0, 3)]), Zone("T2", [(5, 0), (8, 0), (8, 3), (5, 3)]),
         Zone("window", [(0, 8), (10, 8), (10, 10), (0, 10)], "exclude")]


def person(x_m, y_m):  # foot point at (x_m, y_m)
    px, py = x_m * 100, y_m * 100
    return (px - 20, py - 170, px + 20, py)


def trained():
    c = UniformClassifier()
    for _ in range(3):
        c.correct(BLUE, "staff")
    c.correct(SKIN, "guest")
    return c


def simulate(guest_pos_by_table, staff_visits, duration=1500):
    tpl = get_template("casual_dining")
    fp = FloorPipeline(tpl, H, ZONES, trained())
    eng = AlertEngine(tpl)
    alerts, events = [], []
    for t in range(duration):
        dets = []
        for (a, b, pos) in guest_pos_by_table.values():
            if a <= t < b:
                dets += [(RawDet(person(pos[0] + k * 0.5, pos[1]), .9), SKIN) for k in range(2)]
        for (a, b, pos) in staff_visits.values():
            if a <= t < b:
                dets.append((RawDet(person(*pos), .9), BLUE))
        for e in fp.step(float(t), dets):
            events.append(e)
            if (al := eng.process(e)):
                alerts.append((al["tables"][0], al["t"]))
    return events, alerts


def test_neglected_table_is_alerted_attended_table_is_not():
    guests = {"T1": (10, 5000, (1.0, 2.0)), "T2": (10, 5000, (6.0, 2.0))}
    staff = {"T2": (60, 90, (7.5, 2.0))}
    events, alerts = simulate(guests, staff)
    tpl = get_template("casual_dining")
    # T1 never visited -> greet alert; T2 visited at ~60-90 s -> next check-in due 'attended_window' later
    truth = [("T1", 10 + tpl.greet_alert_s), ("T2", 90 + tpl.attended_window_s)]
    s = score_alerts(alerts, truth, window_s=60)
    assert s.precision >= 0.9 and s.recall >= 0.9
    assert abs(s.median_delay_s) <= 60
    assert alerts[0][0] == "T1"  # the attended table is NOT alerted early
    assert "staff_visit" in {e.kind for e in events if e.table == "T2"}


def test_people_in_window_exclusion_zone_never_create_visits():
    events, alerts = simulate({"X": (0, 2000, (1.0, 9.0))}, {})
    assert events == [] and alerts == []


def test_untrained_venue_makes_no_confident_alerts():
    tpl = get_template("casual_dining")
    fp = FloorPipeline(tpl, H, ZONES, UniformClassifier())  # no corrections yet
    out = []
    for t in range(1500):
        out += fp.step(float(t), [(RawDet(person(1.0, 2.0), .9), SKIN)])
    assert not [e for e in out if e.kind in ("seated", "needs_attention")]


def test_stale_camera_freezes_logic():
    tpl = get_template("casual_dining")
    fp = FloorPipeline(tpl, H, ZONES, trained())
    out = []
    for t in range(1500):
        out += fp.step(float(t), [(RawDet(person(1.0, 2.0), .9), SKIN)], stale=True)
    assert {e.kind for e in out} <= {"uncertain"}
