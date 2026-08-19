"""Провижининг на сервере без админ-API — только IMAP/SMTP.

Ключевое ограничение, которое здесь не прячется: **по IMAP ящик создать
нельзя** — в протоколе есть команда CREATE, но она заводит *папку внутри уже
существующего ящика*, а не сам ящик. Поэтому «создание почты на сайте» для
такого сервера означает:

  1. админ (или почтовый администратор) заводит ящик на сервере;
  2. в форме на сайте вводится его адрес и пароль;
  3. платформа проверяет пару живым IMAP-логином — и только при успехе
     привязывает ящик к пользователю, сохраняя пароль зашифрованным
     (``ProvisionedMailbox.encrypted_smtp_app_password``), после чего
     работают и синхронизация писем, и отправка.

Если логин не проходит, строка получает ``status="error"`` и текст ошибки —
админ видит его прямо в таблице ящиков и понимает, что чинить, вместо
«создалось, но почему-то не работает».
"""
from __future__ import annotations

import logging

from apps.mail.services import imap_client
from apps.mail.services.provisioning.base import (
    ProvisioningError,
    RemoteListingUnsupported,
    RemoteMailbox,
)

log = logging.getLogger(__name__)


class ImapProvisioner:
    name = "imap"
    # Голый IMAP не умеет перечислить ящики домена — сверка идёт поштучной
    # проверкой локальных строк (см. reconcile_service).
    can_list_remote = False
    # Ящик должен уже существовать на сервере; платформа его только проверяет.
    can_create = False
    requires_existing_mailbox = True

    def create(
        self, *, local_part: str, domain: str, address: str, password: str,
        full_name: str = "", quota_mb: int = 1024,
    ) -> None:
        if not password:
            raise ProvisioningError(
                "IMAP-сервер не умеет создавать ящики: заведите ящик на сервере "
                "и укажите его пароль — платформа проверит и привяжет его."
            )
        ok, error = imap_client.verify_credentials(address, password)
        if not ok:
            raise ProvisioningError(
                f"Ящик {address} не отвечает на IMAP-логин: {error}. "
                "Проверьте, что он заведён на почтовом сервере и пароль верен."
            )
        log.info("imap_mailbox_verified address=%s", address)

    def update(
        self, *, address: str, full_name: str | None = None, quota_mb: int | None = None,
    ) -> None:
        """Имя и квота живут на почтовом сервере и правятся его админкой —
        локальная строка обновится, наружу идти некуда."""
        log.info("imap_provisioner_update_local_only address=%s", address)

    def reset_password(
        self, *, address: str, new_password: str, force_change: bool = True,
    ) -> None:
        """Сменить пароль по IMAP нельзя — можно только убедиться, что пароль,
        который админ уже поставил на сервере, действительно рабочий, и
        сохранить его у себя (иначе синхронизация и отправка отвалятся)."""
        ok, error = imap_client.verify_credentials(address, new_password)
        if not ok:
            raise ProvisioningError(
                f"Новый пароль для {address} не принят сервером: {error}. "
                "Смените пароль на почтовом сервере, затем повторите здесь тем же значением."
            )

    def set_active(self, *, address: str, active: bool) -> None:
        log.info("imap_provisioner_set_active_noop address=%s active=%s", address, active)

    def delete(self, *, address: str) -> None:
        """Удаление ящика — операция почтового сервера. Локальная строка
        помечается удалённой в любом случае (см. mailbox_service.delete)."""
        log.info("imap_provisioner_delete_local_only address=%s", address)

    def list_remote(self) -> list[RemoteMailbox]:
        raise RemoteListingUnsupported(
            "IMAP-сервер не отдаёт список ящиков домена — сверка идёт "
            "поштучной проверкой сохранённых учёток."
        )

    def verify(self, *, address: str, password: str) -> tuple[bool, str | None]:
        if not password:
            return False, "нет сохранённого пароля для проверки"
        return imap_client.verify_credentials(address, password)

    def exists_remote(self, *, address: str) -> tuple[bool | None, str | None]:
        """«Не знаю» — и это единственный честный ответ.

        В IMAP нет команды «есть ли на сервере ящик X»: проверить можно только
        логином, а пароля у сверки нет. Ответить ``False`` было бы хуже, чем не
        ответить: платформа решила бы, что адрес свободен, и завела бы вторую
        строку поверх живого ящика.
        """
        return None, (
            "IMAP не умеет проверить существование ящика без пароля — "
            "укажите пароль, и платформа проверит учётку логином"
        )
