"""SMTP submission на корпоративный сервер — отправитель провайдера ``imap``.

Парный к ``mailcow_smtp.py``, но без привязки к Mailcow: хост/порт/режим TLS
берутся из ``SMTP_*`` (с откатом на ``IMAP_HOST``, типовой случай «один хост
и для IMAP, и для submission»), а не выводятся из ``MAILCOW_API_URL``.
Логин — адрес ящика, пароль — тот же app-password, что хранится
зашифрованным в ``ProvisionedMailbox.encrypted_smtp_app_password`` и которым
пользуется IMAP-синхронизация.

Через SSH-туннель работает так же прозрачно, как IMAP: SMTP_HOST указывает
на сервис ``mail-tunnel``, а он пробрасывает 587-й порт почтового сервера.

Живой сетевой вызов — в seam-функции ``send_via_smtp``: тесты подменяют
ровно её (или ``smtplib.SMTP``), без сети.
"""
from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage as MimeMessage

from apps.mail.models import ProvisionedMailbox
from apps.mail.services.crypto import crypto_service
from apps.mail.services.mail_config import get_config
from apps.mail.services.sender.base import SendResult
from apps.mail.services.sender.mime import build_mime

log = logging.getLogger(__name__)


def smtp_target() -> tuple[str, int]:
    """Хост и порт submission из эффективных настроек."""
    cfg = get_config()
    return cfg.effective_smtp_host(), cfg.smtp_port


def _smtp_username(account) -> str:
    """Логин для SMTP: у аккаунта со своими реквизитами он может отличаться
    от адреса (бывает «ivanov» вместо «ivanov@example.com»)."""
    if account is not None and account.imap_settings_id is not None:
        return account.imap_settings.username or account.address
    return account.address


def _tls_mode(account) -> tuple[bool, bool]:
    """``(ssl, starttls)`` — режим шифрования для этого аккаунта.

    У подключённого пользователем ящика он свой: gmail хочет 587+STARTTLS,
    Яндекс — 465+SSL, корпоративный туннель — вообще без TLS.
    """
    if account is not None and account.imap_settings_id is not None:
        row = account.imap_settings
        return row.smtp_ssl, row.smtp_starttls
    cfg = get_config()
    return cfg.smtp_ssl, cfg.smtp_starttls


def send_via_smtp(
    mime: MimeMessage, *, host: str, port: int, username: str, password: str,
    sender: str, recipients: list[str], account=None,
) -> None:
    """Единственный живой сетевой вызов модуля."""
    use_ssl, use_starttls = _tls_mode(account)
    timeout = get_config().smtp_timeout
    if use_ssl:
        smtp: smtplib.SMTP = smtplib.SMTP_SSL(host, port, timeout=timeout)
    else:
        smtp = smtplib.SMTP(host, port, timeout=timeout)
    with smtp:
        if not use_ssl and use_starttls:
            smtp.starttls()
        if password:
            smtp.login(username, password)
        smtp.sendmail(sender, recipients, mime.as_bytes())


def build_envelope(account, message) -> tuple[MimeMessage, list[str]]:
    """MIME + envelope-получатели (Bcc — только в конверте, не в заголовках).

    Та же сборка, что и у ``MailcowSmtpSender._build_envelope`` — вынесена
    отдельной функцией, чтобы юнит-тестироваться без похода за паролем.
    """
    mime = build_mime(message, from_address=account.address, from_name=account.display_name)

    bcc_addresses = [r["email"] for r in message.bcc_recipients or [] if r.get("email")]
    if "Bcc" in mime:
        del mime["Bcc"]
    envelope_recipients = sorted(
        {r["email"] for r in message.to_recipients or [] if r.get("email")}
        | {r["email"] for r in message.cc_recipients or [] if r.get("email")}
        | set(bcc_addresses)
    )
    return mime, envelope_recipients


def account_smtp_target(account) -> tuple[str, int]:
    """SMTP-хост аккаунта: свой, если он подключён по IMAP, иначе общий."""
    if account.imap_settings_id is not None:
        row = account.imap_settings
        return row.effective_smtp_host(), row.smtp_port
    return smtp_target()


def resolve_app_password(account) -> tuple[str | None, str | None]:
    """``(логин, пароль)``-пароль аккаунта в открытом виде.

    Для аккаунта со своими реквизитами берём их; для корпоративного —
    app-password выданного ящика.
    """
    if account.imap_settings_id is not None:
        from apps.mail.services import imap_account_service

        credentials = imap_account_service.credentials_for(account)
        if credentials is None:
            return None, "не удалось расшифровать сохранённый пароль"
        return credentials[1], None

    if not account.mailbox_id:
        return None, "corporate account has no mailbox_id"
    mb = ProvisionedMailbox.objects.filter(id=account.mailbox_id).first()
    if mb is None or not mb.encrypted_smtp_app_password:
        return None, "mailbox has no stored password"
    try:
        return crypto_service.decrypt(mb.encrypted_smtp_app_password), None
    except Exception as exc:  # noqa: BLE001 — та же best-effort ветка, что в mailcow_smtp
        return None, f"app-password decrypt: {exc}"


class CorporateSmtpSender:
    provider = "imap"

    def send(self, account, message) -> SendResult:
        password, error = resolve_app_password(account)
        if error:
            return SendResult(error=error)

        host, port = account_smtp_target(account)
        if not host:
            return SendResult(error="SMTP-хост не настроен")

        mime, envelope_recipients = build_envelope(account, message)
        if not envelope_recipients:
            return SendResult(error="no recipients")

        try:
            send_via_smtp(
                mime, host=host, port=port, username=_smtp_username(account),
                password=password or "", sender=account.address,
                recipients=envelope_recipients, account=account,
            )
        except Exception as exc:  # noqa: BLE001 — та же ветка, что в mailcow_smtp
            return SendResult(error=f"smtp: {exc}")

        return SendResult(provider_message_id=mime["Message-ID"])
