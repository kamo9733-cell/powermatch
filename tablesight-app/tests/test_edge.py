from fastapi.testclient import TestClient

from tablesight.edge.agent import Flusher, Outbox
from tablesight.platform.app import Outbox as Mail
from tablesight.platform.app import create_app

PW = "correct-horse-battery"


def test_outage_buffering_and_replay_end_to_end():
    mail = Mail()
    c = TestClient(create_app(outbox=mail))
    c.post("/signup", json={"email": "o@x.com", "password": PW, "org_name": "O"})
    c.post("/verify-email", params={"token": mail.sent[0]["token"]})
    h = {"Authorization": "Bearer " + c.post("/login", json={"email": "o@x.com", "password": PW}).json()["token"]}
    lid = c.post("/locations", params={"name": "L"}, headers=h).json()["id"]
    code = c.post("/pairing", params={"location_id": lid}, headers=h).json()["code"]
    dh = {"Authorization": "Bearer " + c.post("/edge/pair", params={"code": code}).json()["token"]}

    online = {"up": False, "sent": 0}

    def send(batch):
        if not online["up"]:
            raise ConnectionError("wifi down")
        online["sent"] += 1
        r = c.post("/edge/events", json=batch, headers=dh)
        r.raise_for_status()
        # simulate lost ACK: server stored it, client believes failure once
        if online["sent"] == 1:
            raise ConnectionError("ack lost")
        return r.json()

    ob = Outbox()
    for i in range(5):
        ob.add(i, "T1", "seated")
    fl = Flusher(ob, send)
    assert fl.tick(0) is False and len(ob) == 5            # offline: nothing lost
    assert fl.tick(1) is False                             # still in backoff
    online["up"] = True
    assert fl.tick(1000) is False and len(ob) == 5         # ACK lost -> kept
    ob.add(9, "T1", "vacated")
    assert fl.tick(5000) is True and len(ob) == 0          # replay succeeds
    evs = c.get("/events", params={"location_id": lid}, headers=h).json()
    assert len(evs) == 6                                   # no duplicates despite replay
