"""Сверка адреса перед заведением ящика: «а такой ящик уже есть?»

Проблема, которую закрывает модуль: платформа заводила ящик, зная только
СВОЮ таблицу. Ящик ``i.ivanov@htq.group``, созданный почтовым администратором
мимо платформы, для неё не существовал — и она либо молча выдавала сотруднику
второй, пустой ``i.ivanov2@htq.group`` (а почта продолжала копиться в первом),
либо получала от Mailcow отказ на ``/add/mailbox`` и оставляла строку со
``status="error"``.

Сверка смотрит в оба места — локальную строку и почтовый сервер — и отвечает
не «да/нет», а «что с этим делать»: подключить существующий ящик, спросить у
человека пароль или спокойно создавать новый.

Ключевая тонкость — **третье состояние**. У голого IMAP нет команды «есть ли
такой ящик», Mailcow может быть недоступен, а в неконфигурированном окружении
сервера нет вовсе. Во всех трёх случаях честный ответ — «не знаю»
(``checked_remote=False``), и он НЕ равен «ящика нет»: приравняй мы одно к
другому, сверка на IMAP-сервере всегда разрешала бы создание и плодила бы
ровно те дубли, ради которых написана.

Потребители: ``mailbox_service.provision`` (решает, создавать или подключать)
и ручка ``GET /api/email/v1/mailboxes/lookup/`` (показывает вердикт в форме
создания до нажатия кнопки).
"""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass

from django.core.cache import cache

from apps.mail.models import ProvisionedMailbox
from apps.mail.services import mail_config
from apps.mail.services import mailbox_service as mbx_svc
from apps.mail.services.provisioning import get_provisioner, resolve_provisioner_name

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class MailboxLookup:
    """Вердикт сверки по одному адресу."""

    #: нормализованный адрес, по которому шла проверка
    address: str
    #: найден хоть где-нибудь
    exists: bool = False
    #: где именно: ``none`` | ``local`` | ``remote`` | ``both``
    source: str = "none"
    #: удалось ли вообще спросить почтовый сервер (см. докстринг модуля)
    checked_remote: bool = False
    #: почему сервер не ответил — показывается админу как есть
    remote_detail: str | None = None
    #: сериализованная локальная строка, если она есть
    mailbox: dict | None = None
    owner_user_id: int | None = None
    #: ящик уже принадлежит ДРУГОМУ сотруднику — подключать нельзя
    owner_conflict: bool = False
    #: ящик можно подключить вместо создания нового
    can_attach: bool = False
    #: без пароля от человека привязка будет нерабочей
    needs_password: bool = False
    #: человекочитаемый вердикт для интерфейса
    detail: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


def lookup(address: str, *, for_user_id: int | None = None) -> MailboxLookup:
    """Проверить адрес в базе платформы и на почтовом сервере.

    ``for_user_id`` — кому собираются отдать ящик. Без него «занят другим
    пользователем» определить нельзя, поэтому конфликт не диагностируется.
    """
    address = (address or "").strip().lower()
    if not address:
        return MailboxLookup(address="", detail="Адрес не указан")

    # ``iexact`` — сервер мог записать адрес с заглавными; пропустить из-за
    # этого существующий ящик значит завести дубль ровно там, где сверка
    # обязана его предотвратить.
    row = (ProvisionedMailbox.objects
           .filter(address__iexact=address)
           .exclude(status="deleted")
           .first())
    remote, remote_detail = _exists_remote(address)

    has_local = row is not None
    has_remote = remote is True
    source = {
        (True, True): "both",
        (True, False): "local",
        (False, True): "remote",
        (False, False): "none",
    }[(has_local, has_remote)]

    owner_user_id = row.user_id if row is not None else None
    owner_conflict = (
        owner_user_id is not None
        and for_user_id is not None
        and owner_user_id != for_user_id
    )

    exists = has_local or has_remote
    can_attach = exists and not owner_conflict
    needs_password = can_attach and _needs_password(address)

    result = MailboxLookup(
        address=address,
        exists=exists,
        source=source,
        checked_remote=remote is not None,
        remote_detail=remote_detail,
        mailbox=mbx_svc.serialize(row) if row is not None else None,
        owner_user_id=owner_user_id,
        owner_conflict=owner_conflict,
        can_attach=can_attach,
        needs_password=needs_password,
        detail="",
    )
    return _with_detail(result)


def lookup_candidate(
    *, local_part: str = "", first_name: str = "", last_name: str = "",
    email: str = "", user_id: int | None = None,
) -> MailboxLookup:
    """Та же сверка, но по данным формы, а не по готовому адресу.

    Адрес собирается ровно тем же кодом, что и при создании
    (``mailbox_service.resolve_local_part``) — иначе форма показывала бы
    вердикт про один адрес, а создание занимало бы другой.
    """
    domain = mail_config.get_config().domain
    if not domain:
        raise mbx_svc.MailboxDomainNotConfigured

    candidate = _Candidate(
        local_part=local_part, first_name=first_name, last_name=last_name,
        email=email,
    )
    return lookup(
        f"{mbx_svc.resolve_local_part(candidate)}@{domain}", for_user_id=user_id,
    )


@dataclass(frozen=True)
class _Candidate:
    """Минимум полей, которого хватает ``resolve_local_part`` (утиная
    типизация — тот же приём, что и ``interface._MailboxRequest``)."""

    local_part: str = ""
    first_name: str = ""
    last_name: str = ""
    email: str = ""


def _exists_remote(address: str) -> tuple[bool | None, str | None]:
    """``exists_remote`` провижинера, устойчивый к его отсутствию.

    ``getattr``, а не прямой вызов: метод добавлен позже остального
    контракта, и подменённый в тестах или сторонний провижинер без него
    должен означать «не знаю», а не падение сверки.
    """
    provisioner = get_provisioner()
    probe = getattr(provisioner, "exists_remote", None)
    if probe is None:
        return None, "провижинер не умеет проверять существование ящика"
    try:
        return probe(address=address)
    except Exception as exc:  # noqa: BLE001 — сверка не должна ронять создание
        log.warning("exists_remote_failed address=%s: %s", address, exc)
        return None, f"почтовый сервер не ответил: {exc}"


#: Сколько держать ответ почтового сервера про адрес. Пять минут — компромисс
#: между «не долбить Mailcow на каждой загрузке страницы» и «увидеть только что
#: заведённый ящик, не дожидаясь конца дня».
_REMOTE_TTL = 300


def remote_exists(address: str, *, use_cache: bool = False) -> bool | None:
    """Есть ли ящик на почтовом сервере: ``True`` / ``False`` / ``None``.

    Третье состояние — не отговорка, а единственный честный ответ у голого
    IMAP (проверить можно только логином, а пароля нет) и у недоступного
    сервера. Подробнее — в докстринге модуля.

    ``use_cache`` для тех, кто спрашивает ЧАСТО и по неважному поводу: ручка
    ``connect-corporate`` дёргается на каждой загрузке страницы каждым
    сотрудником. Решения о ЗАВЕДЕНИИ ящика кэш не используют намеренно —
    там устаревшее «ящик есть» стоило бы дубля или потерянной почты.

    Кэшируется только ответ сервера: он одинаков для всех спрашивающих.
    Класть в кэш весь ``MailboxLookup`` было бы ошибкой — ``owner_conflict``
    в нём считается относительно конкретного пользователя, и один ключ
    отдавал бы соседу чужой вердикт.
    """
    address = (address or "").strip().lower()
    if not address:
        return None
    if not use_cache:
        return _exists_remote(address)[0]

    key = f"mail:remote-exists:{address}"
    try:
        cached = cache.get(key)
    except Exception:  # noqa: BLE001 — недоступный Redis не повод падать
        log.warning("remote_exists_cache_get_failed address=%s", address, exc_info=True)
        return _exists_remote(address)[0]

    if cached is not None:
        return cached["exists"]

    exists = _exists_remote(address)[0]
    try:
        # Словарь-обёртка, потому что сам ответ бывает None, а None в кэше
        # неотличим от «ничего не лежит».
        cache.set(key, {"exists": exists}, _REMOTE_TTL)
    except Exception:  # noqa: BLE001
        log.warning("remote_exists_cache_set_failed address=%s", address, exc_info=True)
    return exists


def _needs_password(address: str) -> bool:
    """Нужен ли пароль от человека, чтобы привязка вышла рабочей.

    * пароль уже сохранён с прошлого раза — не нужен;
    * ``mailcow`` — платформа выпустит себе отдельный app-password через API;
    * ``none`` — почтового сервера нет вовсе, синхронизировать нечего и
      проверять негде, требовать пароль было бы бессмысленной преградой;
    * ``imap`` — единственный режим, где пароль обязателен: без него нельзя
      ни проверить ящик, ни потом читать его.
    """
    if mbx_svc.stored_password(address):
        return False
    return resolve_provisioner_name() == "imap"


def _with_detail(r: MailboxLookup) -> MailboxLookup:
    """Дописать вердикт словами — его показывают админу дословно."""
    if r.owner_conflict:
        text = (
            f"Ящик {r.address} уже привязан к пользователю #{r.owner_user_id}. "
            f"Для нового сотрудника будет подобран свободный адрес."
        )
    elif not r.exists:
        text = f"Ящик {r.address} свободен — будет создан новый."
        if not r.checked_remote and r.remote_detail:
            text += f" Почтовый сервер не проверялся: {r.remote_detail}."
    elif r.source == "remote":
        text = (
            f"Ящик {r.address} уже есть на почтовом сервере — он будет "
            f"подключён, новый не создаётся."
        )
    elif r.source == "both":
        text = (
            f"Ящик {r.address} есть и в платформе, и на почтовом сервере — "
            f"он будет подключён."
        )
    else:
        text = f"Ящик {r.address} уже заведён в платформе — он будет подключён."

    if r.needs_password:
        text += " Укажите пароль ящика: платформа проверит учётку логином."

    return MailboxLookup(**{**asdict(r), "detail": text})
