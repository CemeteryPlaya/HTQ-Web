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
    # Корпоративный сервер без Mailcow-API: тот же SMTP submission, но хост и
    # режим TLS берутся из SMTP_*/IMAP_HOST (см. corporate_smtp.py).
    if provider == "imap":
        from apps.mail.services.sender.corporate_smtp import CorporateSmtpSender
        return CorporateSmtpSender()
    raise ValueError(f"Unsupported sender provider: {provider!r}")
