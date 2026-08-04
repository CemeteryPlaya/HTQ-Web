"""Mailcow corporate sender — SMTP submission on port 587 STARTTLS. Порт
``services/email/app/services/sender/mailcow_smtp.py``.

mailboxes-под-задача (mail-mailboxes-brief.md) закрывает ограничение,
которое здесь раньше было задокументировано: ``ProvisionedMailbox`` теперь
перенесена (``apps/mail/models.py``), поэтому ``send()`` резолвит
app-password буквально как исходник — ``account.mailbox_id`` ->
``ProvisionedMailbox.encrypted_smtp_app_password`` -> ``crypto_service.
decrypt`` -> ``_send_via_smtp``. Единственное отличие от исходника —
`session.get(ProvisionedMailbox, ...)` (SQLAlchemy AsyncSession) стал
обычным синхронным ``ProvisionedMailbox.objects.filter(...).first()``
(Django ORM, как и everywhere в этом порту).

Реальная транспортная логика (сборка MIME, envelope-получатели без Bcc,
STARTTLS SMTP-отправка) — в seam-функции ``_send_via_smtp``, unit-
тестируемой напрямую (с фейковым ``smtplib.SMTP``) и монkeypatch'имой как
seam в тестах на ``send()`` целиком (без живой сети)."""
from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage as MimeMessage

from django.conf import settings

from apps.mail.models import ProvisionedMailbox
from apps.mail.services.crypto import crypto_service
from apps.mail.services.sender.base import SendResult
from apps.mail.services.sender.mime import build_mime

log = logging.getLogger(__name__)


def _smtp_host() -> str:
    """Хост submission: имя из ``MAILCOW_API_URL``, как в исходнике.

    Откат на ``SMTP_HOST``/``IMAP_HOST`` добавлен для инсталляций, где
    Mailcow-ящики есть, а REST API наружу не выставлен (тогда раньше
    получалась пустая строка и гарантированный отказ отправки) — и для
    доступа через SSH-туннель, где submission живёт на адресе туннеля, а не
    на адресе API.
    """
    from apps.mail.services.mail_config import get_config

    cfg = get_config()
    host = cfg.mailcow_api_url.replace("https://", "").replace("http://", "").split("/")[0]
    return host or cfg.effective_smtp_host()


def _send_via_smtp(
    mime: MimeMessage, *, host: str, port: int, username: str, password: str,
    sender: str, recipients: list[str],
) -> None:
    """Единственный живой сетевой вызов этого модуля — тесты монkeypatch'ят
    ровно эту функцию (или ``smtplib.SMTP`` напрямую)."""
    with smtplib.SMTP(host, port, timeout=30) as smtp:
        smtp.starttls()
        smtp.login(username, password)
        smtp.sendmail(sender, recipients, mime.as_bytes())


class MailcowSmtpSender:
    provider = "mailcow"

    def send(self, account, message) -> SendResult:
        if not account.mailbox_id:
            return SendResult(error="mailcow account has no mailbox_id")

        mb = ProvisionedMailbox.objects.filter(id=account.mailbox_id).first()
        if mb is None or not mb.encrypted_smtp_app_password:
            return SendResult(error="mailcow mailbox has no app-password")
        try:
            password = crypto_service.decrypt(mb.encrypted_smtp_app_password)
        except Exception as exc:  # noqa: BLE001 — буквальный порт исходника
            return SendResult(error=f"app-password decrypt: {exc}")

        mime, envelope_recipients = self._build_envelope(account, message)
        if not envelope_recipients:
            return SendResult(error="no recipients")

        try:
            _send_via_smtp(
                mime, host=_smtp_host(), port=587, username=account.address,
                password=password, sender=account.address, recipients=envelope_recipients,
            )
        except Exception as exc:  # noqa: BLE001 — буквальный порт исходника
            return SendResult(error=f"smtp: {exc}")

        return SendResult(provider_message_id=mime["Message-ID"])

    def _build_envelope(self, account, message) -> tuple[MimeMessage, list[str]]:
        """Реальная (буквальная) сборка MIME + envelope-получателей —
        вынесена отдельно, чтобы быть unit-тестируемой независимо от
        ``send()`` целиком (app-password resolve/decrypt, SMTP-вызов)."""
        mime = build_mime(message, from_address=account.address, from_name=account.display_name)

        bcc_addresses = [r["email"] for r in message.bcc_recipients or [] if r.get("email")]
        if "Bcc" in mime:
            del mime["Bcc"]
        envelope_recipients = list(
            {r["email"] for r in message.to_recipients or [] if r.get("email")}
            | {r["email"] for r in message.cc_recipients or [] if r.get("email")}
            | set(bcc_addresses)
        )
        return mime, envelope_recipients
