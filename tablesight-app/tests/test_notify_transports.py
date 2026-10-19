import json
import re
import smtplib
from email.message import EmailMessage

from tablesight.escalation import Dispatch
from tablesight.notify import (
    ChatWebhookNotifier,
    HttpResponse,
    Message,
    NtfyNotifier,
    RecordingTransport,
    SmtpNotifier,
    TransportError,
    WebhookNotifier,
    WebhookVerifier,
)
from tablesight.notify.messages import BANNED, EN, build_message

MSG = Message("a1", "srv", "Table 4 might like a check-in", "Seated 9 min.", tables=("4",))


def test_webhook_signature_verifies_and_replay_rejected():
    tr = RecordingTransport()
    n = WebhookNotifier("https://h.example/x", b"s3cret", tr, clock=lambda: 1000.0)
    assert n.send(MSG).ok
    req = tr.requests[0]
    v = WebhookVerifier(b"s3cret", tolerance_s=300)
    assert v.verify(req.headers, req.body, now=1010)
    assert not v.verify(req.headers, req.body, now=1020)  # replay
    assert req.headers["X-Tablesight-Delivery"] == "a1:srv"
    assert json.loads(req.body)["tables"] == ["4"]


def test_webhook_rejects_tamper_wrong_secret_and_stale_or_future_ts():
    tr = RecordingTransport()
    WebhookNotifier("https://h", b"k", tr, clock=lambda: 1000.0).send(MSG)
    req = tr.requests[0]
    assert not WebhookVerifier(b"k").verify(req.headers, req.body + b" ", 1000)
    assert not WebhookVerifier(b"other").verify(req.headers, req.body, 1000)
    assert not WebhookVerifier(b"k").verify(req.headers, req.body, 1000 + 301)
    assert not WebhookVerifier(b"k").verify(req.headers, req.body, 1000 - 301)
    assert not WebhookVerifier(b"k").verify({}, req.body, 1000)
    bad = {**req.headers, "X-Tablesight-Timestamp": "abc"}
    assert not WebhookVerifier(b"k").verify(bad, req.body, 1000)


def test_webhook_retryable_on_5xx_and_transport_error():
    tr = RecordingTransport([HttpResponse(503), HttpResponse(400)])
    n = WebhookNotifier("https://h", b"k", tr)
    assert n.send(MSG).retryable
    assert not n.send(MSG).retryable

    def boom(_):
        raise TransportError("down")

    r = WebhookNotifier("https://h", b"k", boom).send(MSG)
    assert not r.ok and r.retryable


def test_ntfy_request_shape_and_auth():
    tr = RecordingTransport()
    n = NtfyNotifier("https://ntfy.example/", {"srv": "floor-a1b2"}, tr, token="tk_x")
    assert n.send(MSG).ok
    r = tr.requests[0]
    assert r.url == "https://ntfy.example/floor-a1b2" and r.method == "POST"
    assert r.headers["X-Title"] == MSG.title and r.headers["X-Priority"] == "3"
    assert r.headers["Authorization"] == "Bearer tk_x" and r.body == b"Seated 9 min."


def test_ntfy_non_ascii_title_goes_in_body_and_bad_topic_refused():
    tr = RecordingTransport()
    n = NtfyNotifier("https://n", {"srv": "ok-topic", "bad": "../x"}, tr)
    n.send(Message("a", "srv", "الطاولة 4", "body"))
    assert "X-Title" not in tr.requests[0].headers
    assert tr.requests[0].body.decode().startswith("الطاولة 4\n")
    assert (
        not n.send(Message("a", "bad", "t", "b")).ok
        and not n.send(Message("a", "zzz", "t", "b")).ok
    )
    assert len(tr.requests) == 1  # nothing sent for invalid topics


class FakeSmtp:
    def __init__(self, fail=None):
        self.sent: list[EmailMessage] = []
        self.fail = fail

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def send_message(self, m):
        if self.fail:
            raise self.fail
        self.sent.append(m)


def test_smtp_builds_message_without_network():
    s = FakeSmtp()
    n = SmtpNotifier("floor@venue.example", {"srv": "sam@venue.example"}, lambda: s)
    assert n.send(MSG).ok
    m = s.sent[0]
    assert m["To"] == "sam@venue.example" and m["Subject"] == MSG.title
    assert "a1.srv" in m["Message-ID"] and "Seated 9 min." in m.get_content()


def test_smtp_failures_and_header_injection():
    n = SmtpNotifier(
        "f@v",
        {"srv": "a@v", "evil": "a@v\nBcc: x@y"},
        lambda: FakeSmtp(smtplib.SMTPServerDisconnected("x")),
    )
    assert n.send(MSG).retryable
    assert not n.send(Message("a", "evil", "t", "b")).ok
    assert not n.send(Message("a", "nobody", "t", "b")).ok
    refused = SmtpNotifier(
        "f@v", {"srv": "a@v"}, lambda: FakeSmtp(smtplib.SMTPRecipientsRefused({}))
    )
    assert not refused.send(MSG).retryable


def test_chat_payload_is_plain_text_and_sanitised():
    tr = RecordingTransport()
    n = ChatWebhookNotifier("https://chat.example/hooks/x", tr)
    n.send(Message("a", "srv", "Table <!channel> & co", "body"))
    p = json.loads(tr.requests[0].body)
    assert set(p) == {"username", "text"}
    assert "<" not in p["text"] and "&" not in p["text"]


def test_copy_has_no_surveillance_or_blame_wording():
    for key, text in EN.items():
        for w in BANNED:
            assert not re.search(rf"\b{w}", text, re.IGNORECASE), (key, w)
    d = Dispatch("a", "lead", "section_lead", 1, 0, "A", ("4", "5"))
    m = build_message(d, minutes=9)
    assert "Sam" not in m.body and "4, 5" in m.body  # tables, never people
    assert build_message(Dispatch("a", "m", "manager", 2, 0, "A", ("4",))).priority == "high"
    assert set(re.findall(r"\{(\w+)\}", " ".join(EN.values()))) <= {
        "table",
        "minutes",
        "n",
        "tables",
        "section",
        "what",
    }
