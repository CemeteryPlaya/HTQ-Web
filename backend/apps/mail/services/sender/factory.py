"""Sender lookup keyed on provider — буквальный порт
``services/email/app/services/sender/factory.py``. Ленивые импорты — тот
же принцип исходника (не тянуть все три провайдерских модуля при первом
использовании любого одного)."""
from __future__ import annotations

from apps.mail.services.sender.base import Sender


def get_sender(provider: str) -> Sender:
    if provider == "google":
        from apps.mail.services.sender.gmail import GmailSender
        return GmailSender()
    if provider == "microsoft":
        from apps.mail.services.sender.graph import GraphSender
        return GraphSender()
    if provider == "mailcow":
        from apps.mail.services.sender.mailcow_smtp import MailcowSmtpSender
        return MailcowSmtpSender()
    raise ValueError(f"Unsupported sender provider: {provider!r}")
