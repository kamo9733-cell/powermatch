"""Slack / Mattermost-compatible incoming-webhook payload ({"text": ...}, optional "username").

Both products accept a JSON body with "text" and "username". We deliberately use plain text
(no bold markers: Slack mrkdwn and Mattermost markdown disagree) and strip < > & so neither
service can interpret link/mention syntax coming from table names.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from .base import DeliveryResult, HttpRequest, HttpTransport, Message, post


def clean(s: str) -> str:
    return s.replace("<", " ").replace(">", " ").replace("&", " and ")


def payload(msg: Message, username: str = "Tablesight") -> dict:
    return {"username": username, "text": f"{clean(msg.title)}\n{clean(msg.body)}"}


@dataclass
class ChatWebhookNotifier:
    url: str
    transport: HttpTransport
    username: str = "Tablesight"
    channel: str = "chat"

    def send(self, msg: Message) -> DeliveryResult:
        body = json.dumps(payload(msg, self.username)).encode()
        headers = {"Content-Type": "application/json"}
        return post(self.channel, self.transport, HttpRequest("POST", self.url, headers, body))
