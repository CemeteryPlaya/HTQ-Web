"""Sender lookup keyed on provider."""

from __future__ import annotations

from app.services.sender.base import Sender


def get_sender(provider: str) -> Sender:
    if provider == "google":
        from app.services.sender.gmail import GmailSender
        return GmailSender()
    if provider == "microsoft":
        from app.services.sender.graph import GraphSender
        return GraphSender()
    if provider == "mailcow":
        from app.services.sender.mailcow_smtp import MailcowSmtpSender
        return MailcowSmtpSender()
    raise ValueError(f"Unsupported sender provider: {provider!r}")
