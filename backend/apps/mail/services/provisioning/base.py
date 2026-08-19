"""Контракт провижининга ящиков: что именно происходит на почтовом сервере,
когда админ нажимает «Создать ящик» на сайте.

Раньше этого слоя не было вовсе: ``mailbox_service.py`` создавал ТОЛЬКО
локальную строку и явно документировал, что реальный вызов наружу отложен
(«Р2»). Отсюда и жалоба «создание почт на сайте не создаёт почты в почтовом
ящике». Слой намеренно сделан подключаемым, потому что разные почтовые
серверы дают разные возможности:

* **Mailcow** — полноценный REST API: ящик создаётся, правится, удаляется.
* **Произвольный IMAP/SMTP-сервер** — админ-API нет вообще. В самом протоколе
  IMAP нет команды «создать ящик», поэтому «создание на сайте» здесь честно
  означает *проверить живым логином, что ящик существует и учётка рабочая, и
  привязать его к пользователю платформы*. Молча делать вид, что ящик создан,
  хуже, чем сказать админу правду.
* **none** — ничего наружу не вызывать (историческое поведение; остаётся
  дефолтом для неконфигурированного окружения, чтобы ничего не сломать).

Все методы либо отрабатывают, либо кидают ``ProvisioningError`` с
человекочитаемым текстом — он попадает в ``ProvisionedMailbox.last_error`` и
показывается в админке ящиков.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class ProvisioningError(RuntimeError):
    """Почтовый сервер отказал (или недоступен)."""


class RemoteListingUnsupported(ProvisioningError):
    """Сервер не умеет перечислять ящики — сверка идёт по-другому.

    Это не поломка: у голого IMAP просто нет команды «список всех ящиков
    домена». ``reconcile_service`` ловит это и переключается на поштучную
    проверку локальных строк живым логином.
    """


@dataclass(frozen=True)
class RemoteMailbox:
    """Ящик, каким его видит почтовый сервер."""

    address: str
    local_part: str = ""
    domain: str = ""
    quota_mb: int = 0
    display_name: str | None = None
    active: bool = True

    @classmethod
    def from_address(cls, address: str, **kw) -> "RemoteMailbox":
        local_part, _, domain = address.partition("@")
        return cls(address=address, local_part=local_part, domain=domain, **kw)


class MailboxProvisioner(Protocol):
    """Реализации: ``mailcow.MailcowProvisioner``, ``imap.ImapProvisioner``,
    ``noop.NoopProvisioner``."""

    name: str
    #: умеет ли сервер отдать список всех ящиков домена одним запросом
    can_list_remote: bool
    #: создаёт ли реально новый ящик на сервере
    can_create: bool
    #: обязан ли ящик УЖЕ существовать на сервере.
    #:
    #: Отличается от ``not can_create``: ``NoopProvisioner`` тоже ничего не
    #: создаёт, но и существования не требует — там ящик живёт только в БД
    #: платформы. Признак влияет на подбор адреса: свободный ``i.ivanov2``
    #: можно подставить за админа, только если адрес НЕ обязан совпадать с
    #: реальным ящиком на сервере.
    requires_existing_mailbox: bool

    def create(
        self, *, local_part: str, domain: str, address: str, password: str,
        full_name: str = "", quota_mb: int = 1024,
    ) -> None: ...

    def update(
        self, *, address: str, full_name: str | None = None, quota_mb: int | None = None,
    ) -> None: ...

    def reset_password(
        self, *, address: str, new_password: str, force_change: bool = True,
    ) -> None: ...

    def set_active(self, *, address: str, active: bool) -> None: ...

    def delete(self, *, address: str) -> None: ...

    def list_remote(self) -> list[RemoteMailbox]: ...

    def verify(self, *, address: str, password: str) -> tuple[bool, str | None]:
        """``(ok, error)`` — жив ли ящик с этой учёткой. Никогда не кидает."""
        ...

    def exists_remote(self, *, address: str) -> tuple[bool | None, str | None]:
        """``(есть ли ящик на сервере, пояснение)``. Никогда не кидает.

        Состояний ТРИ, и это принципиально:

        * ``True``  — ящик на сервере есть, его можно подключить, а не создавать;
        * ``False`` — ящика нет, создание безопасно;
        * ``None``  — **спросить не у кого**: у голого IMAP нет команды «есть ли
          такой ящик» (проверить можно только логином, а пароля у нас нет),
          сервер может быть недоступен, или он не подключён вовсе.

        Слить ``None`` с ``False`` нельзя: тогда сверка на IMAP-сервере всегда
        отвечала бы «ящика нет» и молча плодила бы дубли ровно там, где их
        обещано не плодить.
        """
        ...
