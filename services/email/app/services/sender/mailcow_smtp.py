"""Mailcow corporate sender — SMTP submission on port 587 STARTTLS."""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.settings import settings
from app.models.account import EmailAccount
from app.models.email import EmailMessage
from app.models.mailbox import ProvisionedMailbox
from app.services.crypto import crypto_service
from app.services.sender.base import SendResult
from app.services.sender.mime import build_mime


log = logging.getLogger(__name__)


def _smtp_host() -> str:
    return (
        settings.mailcow_api_url.replace("https://", "")
        .replace("http://", "")
        .split("/")[0]
    )


class MailcowSmtpSender:
    provider = "mailcow"

    async def send(
        self,
        account: EmailAccount,
        message: EmailMessage,
        session: AsyncSession,
    ) -> SendResult:
        if not account.mailbox_id:
            return SendResult(error="mailcow account has no mailbox_id")
        mb = await session.get(ProvisionedMailbox, account.mailbox_id)
        if mb is None or not mb.encrypted_smtp_app_password:
            return SendResult(error="mailcow mailbox has no app-password")
        try:
            password = crypto_service.decrypt(mb.encrypted_smtp_app_password)
        except Exception as exc:
            return SendResult(error=f"app-password decrypt: {exc}")

        mime = build_mime(
            message,
            from_address=account.address,
            from_name=account.display_name,
        )

        # Ensure To/Cc/Bcc are set in the envelope as well — strip Bcc
        # from the visible headers before transmission (RFC 5322).
        bcc_addresses = [
            r["email"] for r in message.bcc_recipients or [] if r.get("email")
        ]
        if "Bcc" in mime:
            del mime["Bcc"]
        envelope_recipients = list(
            {r["email"] for r in message.to_recipients or [] if r.get("email")}
            | {r["email"] for r in message.cc_recipients or [] if r.get("email")}
            | set(bcc_addresses)
        )

        if not envelope_recipients:
            return SendResult(error="no recipients")

        try:
            import aiosmtplib

            await aiosmtplib.send(
                message=mime,
                hostname=_smtp_host(),
                port=587,
                start_tls=True,
                username=account.address,
                password=password,
                sender=account.address,
                recipients=envelope_recipients,
                timeout=30,
            )
        except Exception as exc:  # noqa: BLE001
            return SendResult(error=f"smtp: {exc}")

        return SendResult(provider_message_id=mime["Message-ID"])
