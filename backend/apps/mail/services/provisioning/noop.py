"""Провижининг-заглушка — поведение платформы ДО появления этого слоя.

Нужна для обратной совместимости: в окружении, где не настроены ни
``MAILCOW_API_URL``, ни ``IMAP_HOST`` (локальная разработка, CI, прод до
подключения почтового сервера), создание ящика по-прежнему заводит только
локальную строку и ничего не пытается вызвать наружу. Ни один существующий
тест и ни один сценарий от этого не меняются.
"""
from __future__ import annotations

import logging

from apps.mail.services.provisioning.base import RemoteListingUnsupported, RemoteMailbox

log = logging.getLogger(__name__)


class NoopProvisioner:
    name = "none"
    can_list_remote = False
    can_create = False
    # Ящика на сервере нет и не требуется — он существует только в БД
    # платформы, ровно как до появления этого слоя.
    requires_existing_mailbox = False

    def create(self, *, address: str, **kw) -> None:
        log.info("provisioner_disabled_create_local_only address=%s", address)

    def update(self, *, address: str, **kw) -> None:
        log.debug("provisioner_disabled_update address=%s", address)

    def reset_password(self, *, address: str, **kw) -> None:
        log.info("provisioner_disabled_reset_password address=%s", address)

    def set_active(self, *, address: str, active: bool) -> None:
        log.debug("provisioner_disabled_set_active address=%s", address)

    def delete(self, *, address: str) -> None:
        log.info("provisioner_disabled_delete address=%s", address)

    def list_remote(self) -> list[RemoteMailbox]:
        raise RemoteListingUnsupported(
            "Почтовый сервер не подключён: задайте MAILCOW_API_URL+MAILCOW_API_KEY "
            "или IMAP_HOST, чтобы включить сверку."
        )

    def verify(self, *, address: str, password: str) -> tuple[bool, str | None]:
        return False, "почтовый сервер не подключён"

    def exists_remote(self, *, address: str) -> tuple[bool | None, str | None]:
        """Сервера нет — спрашивать некого. Ящик живёт только в БД платформы,
        поэтому сверка ограничится локальной строкой."""
        return None, "почтовый сервер не подключён"
