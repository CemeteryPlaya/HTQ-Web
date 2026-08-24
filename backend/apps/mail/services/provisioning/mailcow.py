"""Провижининг через Mailcow REST API.

Тот самый вызов, который в исходном FastAPI-поколении жил в
``workers/mailbox_actors.py`` и при переносе на Django был отложен: теперь
он выполняется синхронно из ``mailbox_service`` (как это уже делали
aliases/forwarding во вьюхах — ``views.py`` инстанцирует ``MailcowClient``
напрямую). Отдельный Celery-актор ради одного HTTP-запроса в этой
архитектуре не нужен: админ должен увидеть результат сразу, а не «ящик
создаётся, зайдите позже».

``MailcowClient`` не переписывается — он был перенесён и покрыт тестами
(``tests/test_mailcow_client.py``), здесь только адаптер к общему контракту.
"""
from __future__ import annotations

import logging

from apps.mail.services.mail_config import get_config
from apps.mail.services.mailcow_client import MailcowClient, MailcowError
from apps.mail.services.provisioning.base import ProvisioningError, RemoteMailbox

log = logging.getLogger(__name__)


class MailcowProvisioner:
    name = "mailcow"
    can_list_remote = True
    can_create = True
    requires_existing_mailbox = False

    def __init__(self, client: MailcowClient | None = None) -> None:
        self.client = client or MailcowClient()

    @staticmethod
    def _wrap(action: str, fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except MailcowError as exc:
            raise ProvisioningError(f"Mailcow {action}: {exc}") from exc
        except Exception as exc:  # noqa: BLE001 — сеть/таймаут/битый ответ
            raise ProvisioningError(f"Mailcow {action} failed: {exc}") from exc

    def create(
        self, *, local_part: str, domain: str, address: str, password: str,
        full_name: str = "", quota_mb: int = 1024,
    ) -> None:
        self._wrap(
            "create_mailbox", self.client.create_mailbox,
            local_part=local_part, domain=domain, password=password,
            full_name=full_name, quota_mb=quota_mb, active=True,
        )

    def update(
        self, *, address: str, full_name: str | None = None, quota_mb: int | None = None,
    ) -> None:
        attr: dict[str, str] = {}
        if full_name is not None:
            attr["name"] = full_name
        if quota_mb is not None:
            attr["quota"] = str(quota_mb)
        if not attr:
            return
        self._wrap("edit_mailbox", self.client.edit_mailbox, address, attr)

    def reset_password(
        self, *, address: str, new_password: str, force_change: bool = True,
    ) -> None:
        self._wrap(
            "reset_password", self.client.reset_password,
            address, new_password, force_change=force_change,
        )

    def set_active(self, *, address: str, active: bool) -> None:
        self._wrap("set_active", self.client.set_active, address, active=active)

    def delete(self, *, address: str) -> None:
        self._wrap("delete_mailbox", self.client.delete_mailbox, address)

    def list_remote(self) -> list[RemoteMailbox]:
        domain = get_config().domain
        rows = self._wrap("list_mailboxes", self.client.list_mailboxes, domain)
        result: list[RemoteMailbox] = []
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            address = row.get("username") or row.get("address") or ""
            if not address:
                continue
            result.append(
                RemoteMailbox(
                    address=address,
                    local_part=row.get("local_part") or address.partition("@")[0],
                    domain=row.get("domain") or address.partition("@")[2],
                    quota_mb=_bytes_to_mb(row.get("quota")),
                    display_name=row.get("name") or None,
                    active=str(row.get("active", "1")) in ("1", "True", "true"),
                )
            )
        return result

    def issue_app_password(self, *, address: str, password: str) -> None:
        """Отдельный app-password для IMAP/SMTP — им пользуются
        синхронизация и отправка, чтобы не таскать интерактивный пароль."""
        self._wrap(
            "add_app_password", self.client.add_app_password,
            address=address, app_name="htqweb", password=password,
        )

    def exists_remote(self, *, address: str) -> tuple[bool | None, str | None]:
        """У Mailcow есть API — спрашиваем его, а не гадаем.

        Недоступный Mailcow даёт ``None`` («не знаю»), а НЕ ``False``: ответить
        «ящика нет» из-за сетевого таймаута значило бы разрешить создание дубля
        поверх живого ящика.
        """
        try:
            data = self.client.get_mailbox(address)
        except Exception as exc:  # noqa: BLE001 — сеть/таймаут/битый ответ
            return None, f"Mailcow get_mailbox: {exc}"
        if not data or (isinstance(data, list) and not data):
            return False, "mailbox not found on server"
        return True, None

    def verify(self, *, address: str, password: str) -> tuple[bool, str | None]:
        """Для Mailcow «проверить учётку» = «спросить API, есть ли ящик».

        Пароль здесь не нужен и намеренно игнорируется: у платформы есть
        админский API-ключ, логиниться по IMAP незачем.
        """
        exists, detail = self.exists_remote(address=address)
        if exists:
            return True, None
        return False, detail or "mailbox not found on server"


def _bytes_to_mb(raw) -> int:
    """Mailcow отдаёт квоту в БАЙТАХ, платформа хранит мегабайты."""
    try:
        return int(raw) // (1024 * 1024)
    except (TypeError, ValueError):
        return 0
