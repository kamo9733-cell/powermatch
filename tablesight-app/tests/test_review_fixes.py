"""Regression tests for bugs found by the independent code review."""
from fastapi.testclient import TestClient
from test_security_api import Clock, mkloc, pair, signup

from tablesight.edge.agent import Flusher, Outbox
from tablesight.platform.app import Outbox as Mail
from tablesight.platform.app import create_app


def boot():
    ob, clk = Mail(), Clock()
    app = create_app(outbox=ob, clock=clk)
    c = TestClient(app)
    owner = signup(c, ob, "o@x.com")
    lid = mkloc(c, owner)
    dev, _ = pair(c, owner, lid)
    return c, app, clk, owner, lid, dev


def ev(i, t, kind="seated", table="T1", **d):
    return {"event_id": f"e{i}", "t": t, "table_id": table, "kind": kind, "detail": d}


def test_events_endpoint_returns_newest_not_oldest():
    c, _, clk, owner, lid, dev = boot()
    batch = [ev(i, clk.t - 5000 + i) for i in range(1000)]
    c.post("/edge/events", json=batch, headers=dev).raise_for_status()
    c.post("/edge/events", json=[ev("new", clk.t - 1, "needs_attention")], headers=dev).raise_for_status()
    got = c.get("/events", params={"location_id": lid, "limit": 50}, headers=owner).json()
    assert len(got) == 50 and got[-1]["event_id"] == "enew" and got[0]["t"] <= got[-1]["t"]


def test_ack_finds_new_alert_even_with_huge_history():
    c, app, clk, owner, lid, dev = boot()
    app.state.db.execute("INSERT INTO events SELECT org_id, location_id, 'old'||value, 1.0, 'T9', 'seated', '{}' "
                         "FROM (SELECT org_id, id AS location_id FROM locations), "
                         "(WITH RECURSIVE c(value) AS (SELECT 1 UNION ALL SELECT value+1 FROM c WHERE value<3000) SELECT value FROM c)")
    c.post("/edge/events", json=[ev("hot", clk.t - 1, "needs_attention")], headers=dev)
    r = c.post("/alerts/ack", params={"location_id": lid, "event_id": "ehot"}, headers=owner)
    assert r.status_code == 200
    row = app.state.db.execute("SELECT payload FROM corrections WHERE kind='ack'").fetchone()
    assert '"table": "T1"' in row["payload"] and '"t"' in row["payload"]


def test_same_event_id_at_two_locations_does_not_collide():
    ob, clk = Mail(), Clock()
    c = TestClient(create_app(outbox=ob, clock=clk))
    owner = signup(c, ob, "o@x.com")
    c.post("/billing/plan", params={"plan": "pro"}, headers=owner)
    l1, l2 = mkloc(c, owner, "A"), mkloc(c, owner, "B")
    d1, _ = pair(c, owner, l1)
    d2, _ = pair(c, owner, l2)
    assert c.post("/edge/events", json=[ev(1, clk.t - 5)], headers=d1).json()["accepted"] == 1
    assert c.post("/edge/events", json=[ev(1, clk.t - 5, "needs_attention")], headers=d2).json()["accepted"] == 1


def test_skewed_edge_clock_is_parked_not_lost_and_correctable():
    c, _, clk, owner, lid, dev = boot()
    ob = Outbox()
    ahead = clk.t + 7200
    ob.add(ahead, "T1", "seated")                         # edge clock 2h ahead: server will refuse it
    ob.add(ahead, "T2", "seated", correct=lambda t: t - 7200)  # corrected at source via ClockSync.correct
    fl = Flusher(ob, lambda b: c.post("/edge/events", json=b, headers=dev).json())
    assert fl.tick(0) is True
    assert len(ob) == 0 and ob.parked_count() == 1        # refused event kept in dead-letter, not deleted
    got = c.get("/events", params={"location_id": lid}, headers=owner).json()
    assert [e["table_id"] for e in got] == ["T2"]


def test_flusher_survives_thousands_of_failures():
    ob = Outbox()
    ob.add(1.0, "T1", "seated")
    def boom(_):
        raise ConnectionError
    fl = Flusher(ob, boom, base_s=2.5)
    for i in range(1500):
        fl.tick(float(i) * 1e6)                            # previously OverflowError at ~1024 failures
    assert len(ob) == 1


def test_retention_purge_enforced_per_location_and_idempotent():
    c, app, clk, owner, lid, dev = boot()
    day = 86400
    c.post("/edge/events", json=[ev("old", clk.t - 40 * day), ev("fresh", clk.t - 2 * day)], headers=dev)
    # default retention is 30 days: the 40-day-old event must go, the fresh one stays
    app.state.db.execute("UPDATE events SET t=? WHERE event_id='eold'", (clk.t - 40 * day,))
    out = app.state.purge()
    assert out["events"] == 1
    ids = [e["event_id"] for e in c.get("/events", params={"location_id": lid}, headers=owner).json()]
    assert ids == ["efresh"]
    assert app.state.purge()["events"] == 0
    c.patch(f"/locations/{lid}/settings", params={"retention_days": 1}, headers=owner)
    assert app.state.purge()["events"] == 1


def test_digest_stays_open_until_every_table_is_resolved():
    from test_escalation import team

    from tablesight.escalation import AlertRouter
    e = team()
    r = AlertRouter(e, min_gap_s=90)
    r.submit("T1", "A", 0, "live")
    r.submit("T2", "A", 10, "live")
    r.submit("T3", "A", 20, "digest")
    out = r.flush(100)
    aid = out[0].alert_id
    r.table_resolved("T2", 110)
    assert e.status(aid) != "resolved"          # T3 is still waiting; previously this closed the whole digest
    r.table_resolved("T3", 120)
    assert e.status(aid) == "resolved"


def test_pairing_rejects_lookalike_localhost_hosts(tmp_path):
    import pytest

    from tablesight.edge.pairing import PairingError, pair
    ok = lambda url: (200, {"token": "t", "device_id": "d"})
    for bad in ("http://localhost.attacker.example", "http://127.0.0.1.evil.io", "http://example.com"):
        with pytest.raises(PairingError):
            pair(bad, "123", tmp_path / "c.json", post=ok)
    assert pair("http://localhost:8080", "123", tmp_path / "c.json", post=ok)["device_id"] == "d"
    assert pair("https://x.example", "123", tmp_path / "c2.json", post=ok)["device_id"] == "d"


def test_forecast_ignores_nan_history():
    from tablesight import forecast as F
    hist = {(d, 12): 50.0 for d in range(1, 30)}
    hist[(29, 12)] = float("nan")
    r = F.ewma_ratio(hist, 30, 12)
    assert (not r.ok) or (r.point == r.point and r.high == r.high)  # never ok=True with NaN
