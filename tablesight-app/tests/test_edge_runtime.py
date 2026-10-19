import json
import os
import stat

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from tablesight.edge import clock, motion, onvif, pairing, source, updates
from tablesight.edge.agent import Outbox
from tablesight.edge.health import CameraHealth, Heartbeat
from tablesight.platform.app import Outbox as Mail
from tablesight.platform.app import create_app

PW = "correct-horse-battery"

# ---- sources ---------------------------------------------------------------------------------


class FakeCap:
    def __init__(self, target, opened=True):
        self.target, self.opened, self.released, self.n = target, opened, False, 0

    def isOpened(self):
        return self.opened

    def read(self):
        self.n += 1
        return (self.n <= 2, b"img")

    def release(self):
        self.released = True


class FakeCv2:
    def __init__(self, opened=True):
        self.opened, self.cap = opened, None

    def VideoCapture(self, target):
        self.cap = FakeCap(target, self.opened)
        return self.cap


def test_rtsp_source_reads_then_signals_end_and_releases():
    cv = FakeCv2()
    s = source.RtspSource("rtsp://u:p@cam/stream", cv2_loader=lambda: cv, clock=lambda: 7.0)
    assert s.open() and s.read() == source.Frame(7.0, b"img") and s.read() and s.read() is None
    s.close()
    assert cv.cap.released and s.read() is None
    assert "u:p" not in repr(s)


def test_source_open_failure_and_url_validation():
    s = source.FileSource("x.mp4", cv2_loader=lambda: FakeCv2(opened=False))
    assert s.open() is False
    with pytest.raises(ValueError):
        source.RtspSource("http://evil/")


def test_missing_opencv_is_a_clear_error():
    def boom():
        raise source.OpenCVMissing("nope")
    with pytest.raises(source.OpenCVMissing):
        source.FileSource("x", cv2_loader=boom).open()


def test_list_source():
    s = source.ListSource([source.Frame(1, b"a")])
    assert s.open() and s.read().t == 1 and s.read() is None


# ---- onvif -----------------------------------------------------------------------------------

CANNED = b"""<?xml version="1.0"?>
<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"
 xmlns:a="http://schemas.xmlsoap.org/ws/2004/08/addressing"
 xmlns:d="http://schemas.xmlsoap.org/ws/2005/04/discovery">
<s:Body><d:ProbeMatches><d:ProbeMatch>
<a:EndpointReference><a:Address>urn:uuid:abc-123</a:Address></a:EndpointReference>
<d:Types>dn:NetworkVideoTransmitter</d:Types>
<d:Scopes>onvif://www.onvif.org/name/Door%20Cam onvif://www.onvif.org/hardware/IPC-1</d:Scopes>
<d:XAddrs>http://192.168.1.50:80/onvif/device_service http://[fe80::1]/onvif/device_service</d:XAddrs>
</d:ProbeMatch></d:ProbeMatches></s:Body></s:Envelope>"""


def test_probe_is_wellformed_and_targets_nvt():
    import xml.etree.ElementTree as ET
    root = ET.fromstring(onvif.build_probe("uuid:1"))
    assert root.findtext(f".//{{{onvif.NS_A}}}Action").endswith("/Probe")
    assert "NetworkVideoTransmitter" in root.findtext(f".//{{{onvif.NS_D}}}Types")


def test_parse_probe_match():
    (d,) = onvif.parse_probe_match(CANNED)
    assert d.address == "urn:uuid:abc-123" and d.hardware == "IPC-1" and d.name == "Door%20Cam"
    assert d.hosts[0] == "192.168.1.50" and len(d.xaddrs) == 2


@pytest.mark.parametrize("bad", [b"", b"<not xml", b"<a/>", b"<!DOCTYPE x [<!ENTITY y 'z'>]><a/>", b"x" * 70000])
def test_parse_rejects_garbage(bad):
    assert onvif.parse_probe_match(bad) == []


# ---- motion + fps ----------------------------------------------------------------------------


def test_motion_gate():
    g = motion.MotionGate(threshold=4, stride=1)
    a, b = bytes([10] * 100), bytes([200] * 100)
    assert g.moving(a) is False      # first frame: nothing to compare
    assert g.moving(a) is False      # identical
    assert g.moving(b) is True
    assert g.moving(bytes(50)) is True  # resolution change


def test_idle_camera_costs_near_zero_and_ramps():
    f = motion.AdaptiveFps()
    for t in range(600):
        f.observe(False, float(t))
    assert f.fps == f.p.idle_fps and not f.active
    assert motion.AdaptiveFps.should_detect(False, f.active) is False
    assert f.observe(True, 1000.0) == f.p.active_fps and f.active
    assert f.observe(False, 1005.0) == f.p.active_fps          # inside hold window
    prev = f.observe(False, 1011.0)
    assert f.p.idle_fps < prev < f.p.active_fps                 # decaying
    for t in range(1012, 1100):
        f.observe(False, float(t))
    assert f.fps == f.p.idle_fps


# ---- pairing + heartbeat against the real platform app ---------------------------------------


def _platform():
    mail = Mail()
    c = TestClient(create_app(outbox=mail))
    c.post("/signup", json={"email": "o@x.com", "password": PW, "org_name": "O"})
    c.post("/verify-email", params={"token": mail.sent[0]["token"]})
    h = {"Authorization": "Bearer " + c.post("/login", json={"email": "o@x.com", "password": PW}).json()["token"]}
    lid = c.post("/locations", params={"name": "L"}, headers=h).json()["id"]
    code = c.post("/pairing", params={"location_id": lid}, headers=h).json()["code"]
    return c, h, code


def test_pair_against_real_platform_and_token_is_0600(tmp_path):
    c, _, code = _platform()

    def post(url):
        assert url.startswith("http://localhost/edge/pair?code=")
        r = c.post(url.removeprefix("http://localhost"))
        return r.status_code, r.json() if r.status_code == 200 else {}

    store = tmp_path / "s" / "device.json"
    out = pairing.pair("http://localhost", code, store, post)
    assert stat.S_IMODE(os.stat(store).st_mode) == 0o600
    creds = pairing.load_credentials(store)
    assert creds["device_id"] == out["device_id"]
    assert c.post("/edge/heartbeat", json={}, headers={"Authorization": "Bearer " + creds["token"]}).status_code == 200
    with pytest.raises(pairing.PairingError):  # single-use code
        pairing.pair("http://localhost", code, tmp_path / "again.json", post)
    assert not (tmp_path / "again.json").exists()
    os.chmod(store, 0o644)
    with pytest.raises(pairing.PairingError):
        pairing.load_credentials(store)


def test_pair_refuses_cleartext_remote():
    with pytest.raises(pairing.PairingError):
        pairing.pair("http://example.com", "1", None, lambda u: (200, {}))


def test_heartbeat_payload_and_server_accepts_it():
    cams = [CameraHealth("c1", True, 99.0, 4.567), CameraHealth("c2", True, 10.0), CameraHealth("c3", False, reconnects=3)]
    ob = Outbox()
    ob.add(1, "T1", "seated")
    p = Heartbeat("1.0.0", cams).payload(100.0, len(ob), 0.5)
    assert [p["cameras"][k]["status"] for k in ("c1", "c2", "c3")] == ["ok", "stale", "down"]
    assert p["cameras_ok"] == 1 and p["cameras_total"] == 3 and p["outbox_depth"] == 1

    c, h, code = _platform()
    tok = c.post("/edge/pair", params={"code": code}).json()["token"]
    r = c.post("/edge/heartbeat", params={"version": "1.0.0"}, json=p, headers={"Authorization": "Bearer " + tok})
    assert r.status_code == 200
    (dev,) = c.get("/devices", headers=h).json()
    assert dev["version"] == "1.0.0" and json.loads(dev["health"])["cameras_total"] == 3


def test_main_beat_builds_authenticated_call():
    from tablesight.edge.__main__ import beat
    seen = []
    beat({"api": "https://a/", "token": "T"}, Heartbeat("2.0"), Outbox(),
         lambda url, body, tok: seen.append((url, tok)) or 200, 5.0)
    assert seen == [("https://a/edge/heartbeat?version=2.0", "T")]


# ---- signed updates --------------------------------------------------------------------------

KEY = Ed25519PrivateKey.generate()
PUB = KEY.public_key()
BLOB = b"wheel-bytes"


def _manifest(version="1.1.0", blob=BLOB):
    import hashlib
    return {"version": version, "sha256": hashlib.sha256(blob).hexdigest(), "url": "https://x/w.whl"}


def test_valid_update_accepted():
    m = updates.verify(updates.sign(_manifest(), KEY), PUB, "1.0.9")
    updates.verify_artifact(m, BLOB)


def test_update_rejections():
    env = updates.sign(_manifest(), KEY)
    tampered = json.loads(json.dumps(env))
    tampered["manifest"]["url"] = "https://evil/w.whl"
    other = updates.sign(_manifest(), Ed25519PrivateKey.generate())
    for bad in (tampered, other, {"manifest": env["manifest"]}, {}, {"manifest": env["manifest"], "signature": "zz"}):
        with pytest.raises(updates.UpdateRejected):
            updates.verify(bad, PUB, "1.0.0")
    for v in ("1.0.0", "0.9"):
        with pytest.raises(updates.UpdateRejected, match="downgrade"):
            updates.verify(updates.sign(_manifest(v), KEY), PUB, "1.0.0")
    with pytest.raises(updates.UpdateRejected):
        updates.verify(updates.sign({**_manifest(), "version": "latest"}, KEY), PUB, "1.0.0")
    with pytest.raises(updates.UpdateRejected, match="hash"):
        updates.verify_artifact(env["manifest"], b"swapped")


def test_version_ordering_is_numeric():
    assert updates.parse_version("1.10.0") > updates.parse_version("1.9.9")


# ---- clock -----------------------------------------------------------------------------------


def test_clock_drift_and_correction():
    times = iter([100.0, 100.2])  # RTT 0.2
    cs = clock.ClockSync()
    assert cs.measure(lambda: 160.1, lambda: next(times))  # server 60 s ahead
    assert cs.offset == pytest.approx(60.0) and cs.drifting()
    assert cs.correct(200.0) == pytest.approx(260.0)


def test_clock_ignores_bad_link_and_parses_http_date():
    ts = iter([0.0, 30.0])
    cs = clock.ClockSync()
    assert cs.measure(lambda: 5.0, lambda: next(ts)) is False and not cs.synced and not cs.drifting()
    assert clock.parse_http_date("Mon, 19 Oct 2026 12:00:00 GMT") == 1792411200.0
