"""Notifier interface and the injected-transport types every channel shares.

Nothing here touches the network: channels build a request and hand it to a transport
callable. Tests pass a fake transport; production passes `urllib_transport`.
"""

from __future__ import annotations

import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class Message:
    alert_id: str
    recipient: str  # staff id; channels map it to an address/topic via their directory
    title: str
    body: str
    priority: str = "normal"  # low | normal | high
    tables: tuple[str, ...] = ()
    click_url: str | None = None


@dataclass(frozen=True)
class DeliveryResult:
    ok: bool
    channel: str
    status: int | None = None
    detail: str = ""
    retryable: bool = False


@dataclass(frozen=True)
class HttpRequest:
    method: str
    url: str
    headers: dict[str, str]
    body: bytes


@dataclass(frozen=True)
class HttpResponse:
    status: int
    body: bytes = b""


class TransportError(Exception):
    """Raised by a transport when the request could not be completed at all."""


HttpTransport = Callable[[HttpRequest], HttpResponse]


class Notifier(Protocol):
    channel: str

    def send(self, msg: Message) -> DeliveryResult: ...


def urllib_transport(timeout_s: float = 10.0) -> HttpTransport:
    """Real transport (stdlib). Only http(s) URLs are allowed. Not used by any test."""

    def send(req: HttpRequest) -> HttpResponse:
        if not req.url.lower().startswith(("https://", "http://")):
            raise TransportError("only http(s) URLs are allowed")
        r = urllib.request.Request(req.url, data=req.body, headers=req.headers, method=req.method)
        try:
            with urllib.request.urlopen(r, timeout=timeout_s) as resp:
                return HttpResponse(resp.status, resp.read())
        except urllib.error.HTTPError as e:
            return HttpResponse(e.code, e.read())
        except OSError as e:
            raise TransportError(str(e)) from e

    return send


def result_from_http(channel: str, resp: HttpResponse) -> DeliveryResult:
    ok = 200 <= resp.status < 300
    retryable = resp.status == 429 or resp.status >= 500
    return DeliveryResult(ok, channel, resp.status, "" if ok else f"http {resp.status}", retryable)


def post(channel: str, transport: HttpTransport, req: HttpRequest) -> DeliveryResult:
    try:
        return result_from_http(channel, transport(req))
    except (TransportError, OSError) as e:
        return DeliveryResult(False, channel, None, f"transport: {e}", retryable=True)


@dataclass
class RecordingTransport:
    """Test/dev transport: records requests, replies with queued (or 200) responses."""

    responses: list[HttpResponse] = field(default_factory=list)
    requests: list[HttpRequest] = field(default_factory=list)

    def __call__(self, req: HttpRequest) -> HttpResponse:
        self.requests.append(req)
        return self.responses.pop(0) if self.responses else HttpResponse(200)
