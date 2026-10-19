"""E-mail via stdlib smtplib. The SMTP connection factory is injected (no sockets in tests)."""

from __future__ import annotations

import smtplib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import make_msgid
from typing import Any

from .base import DeliveryResult, Message


@dataclass
class SmtpNotifier:
    sender: str
    addresses: Mapping[str, str]  # staff id -> e-mail address
    connect: Callable[
        [], Any
    ]  # returns a context manager exposing send_message(), e.g. smtplib.SMTP
    channel: str = "smtp"

    def build(self, msg: Message, to: str) -> EmailMessage:
        em = EmailMessage()
        em["From"] = self.sender
        em["To"] = to
        em["Subject"] = msg.title
        # Stable id per alert+recipient so a retried send is recognisable as the same message.
        em["Message-ID"] = make_msgid(
            idstring=f"{msg.alert_id}.{msg.recipient}", domain="tablesight.invalid"
        )
        em["Auto-Submitted"] = "auto-generated"
        em.set_content(msg.body)
        return em

    def send(self, msg: Message) -> DeliveryResult:
        to = self.addresses.get(msg.recipient)
        if not to or "\n" in to or "\r" in to:
            return DeliveryResult(False, self.channel, None, "no valid address for recipient")
        try:
            with self.connect() as smtp:
                smtp.send_message(self.build(msg, to))
        except smtplib.SMTPRecipientsRefused:
            return DeliveryResult(False, self.channel, None, "recipient refused", retryable=False)
        except (smtplib.SMTPException, OSError) as e:
            return DeliveryResult(False, self.channel, None, f"smtp: {e}", retryable=True)
        return DeliveryResult(True, self.channel, 250)
