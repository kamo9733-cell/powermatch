import itertools

from tablesight.notify.adaptive import MAX_MULT, AlertBudget, adapt, busyness, daypart
from tablesight.templates import TEMPLATES


def test_threshold_never_below_template_floor_any_template_hour_occupancy():
    for tpl, hour, occ in itertools.product(
        TEMPLATES.values(), range(24), [i / 20 for i in range(21)]
    ):
        a = adapt(tpl, hour, occ)
        if tpl.table_service and tpl.greet_alert_s > 0:
            assert tpl.greet_alert_s <= a.threshold_s <= tpl.greet_alert_s * MAX_MULT
        else:
            assert a.mode == "off" and a.threshold_s is None


def test_floor_holds_for_per_venue_overrides():
    from tablesight.templates import get_template

    tpl = get_template("casual_dining", greet_alert_s=100)
    assert min(adapt(tpl, h, o / 10).threshold_s for h in range(24) for o in range(11)) >= 100


def test_rush_raises_and_digests_quiet_is_tighter():
    tpl = TEMPLATES["casual_dining"]
    rush, normal, quiet = (adapt(tpl, 19, o) for o in (0.95, 0.6, 0.1))
    assert rush.mode == "digest" and normal.mode == quiet.mode == "live"
    assert rush.threshold_s > normal.threshold_s > quiet.threshold_s >= tpl.greet_alert_s
    assert rush.min_gap_s > quiet.min_gap_s >= 90


def test_quiet_off_peak_sits_exactly_on_floor():
    tpl = TEMPLATES["fine_dining"]
    assert adapt(tpl, 8, 0.1).threshold_s == tpl.greet_alert_s


def test_labels():
    assert daypart(12) == "lunch" and daypart(19) == "dinner" and daypart(2) == "late"
    assert busyness(0.9) == "rush" and busyness(0.5) == "normal" and busyness(0.1) == "quiet"


def test_budget_rolling_window():
    b = AlertBudget(max_per_hour=2)
    b.record("m", 0)
    b.record("m", 10)
    assert not b.allow("m", 20) and b.allow("other", 20)
    assert b.allow("m", 3600)  # first one aged out of the window
