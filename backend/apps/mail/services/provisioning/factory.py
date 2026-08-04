"""Выбор провижинера по настройкам (``MAIL_PROVISIONER``).

``auto`` (дефолт) разбирается сам и не требует ничего трогать при
подключении почтового сервера — достаточно задать его реквизиты в env:

    MAILCOW_API_URL + MAILCOW_API_KEY  → mailcow
    иначе IMAP_HOST                    → imap
    иначе                              → none (локальная строка, как раньше)

Явные значения ``mailcow``/``imap``/``none`` перекрывают автовыбор.
"""
from __future__ import annotations

import logging

from apps.mail.services.mail_config import get_config
from apps.mail.services.provisioning.base import (  # noqa: F401 — реэкспорт
    MailboxProvisioner,
    ProvisioningError,
    RemoteListingUnsupported,
    RemoteMailbox,
)

log = logging.getLogger(__name__)


def resolve_provisioner_name() -> str:
    cfg = get_config()
    configured = (cfg.provisioner or "auto").strip().lower()
    if configured in ("mailcow", "imap", "none"):
        return configured
    if configured != "auto":
        log.warning("unknown_mail_provisioner value=%r — falling back to auto", configured)
    if cfg.mailcow_configured:
        return "mailcow"
    if cfg.imap_configured:
        return "imap"
    return "none"


def get_provisioner() -> MailboxProvisioner:
    name = resolve_provisioner_name()
    if name == "mailcow":
        from apps.mail.services.provisioning.mailcow import MailcowProvisioner
        return MailcowProvisioner()
    if name == "imap":
        from apps.mail.services.provisioning.imap import ImapProvisioner
        return ImapProvisioner()
    from apps.mail.services.provisioning.noop import NoopProvisioner
    return NoopProvisioner()


def describe() -> dict:
    """Состояние подключения — отдаётся в UI, чтобы админ видел, что именно
    произойдёт при нажатии «Создать ящик», а не гадал."""
    name = resolve_provisioner_name()
    cfg = get_config()
    return {
        "provisioner": name,
        "domain": cfg.domain,
        "mailcow_api_configured": cfg.mailcow_configured,
        "imap_configured": cfg.imap_configured,
        "imap_host": cfg.imap_host,
        "imap_port": cfg.imap_port,
        # true  → сервер заведёт новый ящик сам;
        # false → ящик должен уже существовать, платформа его проверит и привяжет.
        "can_create_remotely": name == "mailcow",
        "can_list_remote": name == "mailcow",
        # Может ли сотрудник подключить свой ящик сам (см. вкладку «Подключение»).
        "allow_self_service": cfg.allow_self_service and name != "none",
    }
