"""ntfy publish-protocol client (https://github.com/binwiederhier/ntfy).

Licence note: ntfy is dual-licensed Apache-2.0 / GPLv2 (repo root has LICENSE = Apache 2.0 text
and LICENSE.GPLv2). We copy no ntfy code and bundle nothing: this is an independent client of its
documented HTTP publish API (POST <server>/<topic>, body = message, X-Title / X-Priority / X-Tags /
X-Click headers, optional "Authorization: Bearer <token>"). If code were ever vendored we would
rely on the Apache-2.0 option. The server is self-hostable, so no third party is required.
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

from .base import DeliveryResult, HttpRequest, HttpTransport, Message, post

_TOPIC = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_PRIORITY = {"low": "2", "normal": "3", "high": "4"}  # 1..5 per ntfy docs; we never use 5 (urgent)


@dataclass
class NtfyNotifier:
    server: str  # e.g. https://ntfy.example.com
    topics: Mapping[str, str]  # staff id -> topic (treat as a secret; use unguessable names)
    transport: HttpTransport
    token: str | None = None
    channel: str = "ntfy"

    def send(self, msg: Message) -> DeliveryResult:
        topic = self.topics.get(msg.recipient, "")
        if not _TOPIC.match(topic):
            return DeliveryResult(False, self.channel, None, "no valid topic for recipient")
        headers = {
            "X-Priority": _PRIORITY.get(msg.priority, "3"),
            "X-Tags": "bell",
            "Content-Type": "text/plain; charset=utf-8",
        }
        text = msg.body
        # HTTP headers are not safe for non-ASCII; keep the title in the body in that case.
        if msg.title.isascii():
            headers["X-Title"] = msg.title
        else:
            text = f"{msg.title}\n{msg.body}"
        if msg.click_url:
            headers["X-Click"] = msg.click_url
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        url = f"{self.server.rstrip('/')}/{topic}"
        return post(self.channel, self.transport, HttpRequest("POST", url, headers, text.encode()))
