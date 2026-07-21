"""Mailcow corporate sender — SMTP submission on port 587 STARTTLS. Порт
``services/email/app/services/sender/mailcow_smtp.py``.

**Ограничение зоны mail-messages (задокументированная странность):**
исходник резолвит app-password через
``ProvisionedMailbox.encrypted_smtp_app_password`` (``account.mailbox_id``
→ ``ProvisionedMailbox`` строка). ``ProvisionedMailbox`` — модель под-задачи
mailboxes, которая ещё НЕ перенесена в этот Django-порт (вне зоны
mail-messages — см. ``apps/mail/models.py::EmailAccount`` докстринг и
``tests/test_stretch.py::test_mailbox_id_fk_todo_is_tracked``). До её
прихода ``MailcowSmtpSender.send`` не может резолвить пароль вообще —
поэтому ветка "нет app-password" исходника (``SendResult(error="mailcow
mailbox has no app-password")``) здесь СРАБАТЫВАЕТ ВСЕГДА для аккаунтов с
заданным ``mailbox_id`` (не деградация: это ТА ЖЕ ошибка, которую вернул бы
исходник до провижининга ящика — здесь она наступает раньше, по структурной
причине, а не потому что мы её выдумали). Ветка "нет mailbox_id вовсе"
переносится буквально и полностью реальна (``account.mailbox_id`` — обычное
поле уже в этом порту).

Реальная транспортная логика (сборка MIME, envelope-получатели без Bcc,
STARTTLS SMTP-отправка) переносится буквально в seam-функцию
``_send_via_smtp`` — она unit-тестируется напрямую (с фейковым
``smtplib.SMTP``), даже если сама ``MailcowSmtpSender.send`` не может её
достичь до прихода ``ProvisionedMailbox``."""
from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage as MimeMessage

from django.conf import settings

from apps.mail.services.sender.base import SendResult
from apps.mail.services.sender.mime import build_mime

log = logging.getLogger(__name__)


def _smtp_host() -> str:
    url = getattr(settings, "MAILCOW_API_URL", "")
    return url.replace("https://", "").replace("http://", "").split("/")[0]


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

        # ProvisionedMailbox не перенесена (см. модуль docstring) —
        # структурно невозможно резолвить app-password до под-задачи
        # mailboxes. Буквально та же ошибка, что вернул бы исходник для
        # ещё не провижининг-нутого ящика.
        return SendResult(
            error="mailcow mailbox has no app-password "
                  "(ProvisionedMailbox not yet migrated — mailboxes sub-task)",
        )

    def _build_envelope(self, account, message) -> tuple[MimeMessage, list[str]]:
        """Реальная (буквальная) сборка MIME + envelope-получателей —
        вынесена отдельно, чтобы быть unit-тестируемой независимо от
        ``send()``'s текущего структурного ограничения выше."""
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
