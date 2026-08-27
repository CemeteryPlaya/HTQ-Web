"""Mailbox provisioning service — порт
``services/email/app/services/mailbox_service.py`` (mailboxes-под-задача,
mail-mailboxes-brief.md).

Раньше этот модуль работал ТОЛЬКО с локальной строкой: реальный вызов на
почтовый сервер был отложен («Р2»: dramatiq-актор ``mailbox_actors.py`` не
портировался). Из-за этого ящик, «созданный» на сайте, на почтовом сервере
не появлялся. Теперь каждая операция после локального перехода дёргает
``services/provisioning`` — подключаемый слой, который знает, что именно
умеет конкретный почтовый сервер (Mailcow REST API / голый IMAP / ничего).

Как распределены ответственности при ошибке сервера:

* **Локальный переход выполняется всегда** — ровно как раньше, поэтому все
  существующие коды ответов (404/409/…) сохранены дословно.
* **Отказ сервера не откатывает строку молча**: он попадает в
  ``ProvisionedMailbox.last_error``, а для create/reset-password ещё и
  переводит строку в ``status="error"`` — админка ящиков показывает это
  прямо в таблице (колонка адреса рисует ``last_error`` красным).
* В неконфигурированном окружении провижинер — ``NoopProvisioner``, то есть
  поведение бит-в-бит прежнее (обратная совместимость).

Username autogen rule (i.ivanov from "Иван Иванов"):
  - Cyrillic → Latin via small translit table (mirrors hr/department_service)
  - first letter of first_name + "." + lowercased last_name, alnum-only
  - On conflict, append numeric suffix: i.ivanov, i.ivanov2, i.ivanov3, …
    (только когда сервер умеет заводить ящики сам; для IMAP-режима адрес
    обязан совпасть с уже существующим на сервере, поэтому там занятый
    адрес — это 409, а не тихое переименование)
"""
from __future__ import annotations

import logging
import re
import secrets
import string
from dataclasses import dataclass

from django.conf import settings
from django.db import transaction
from django.utils import timezone as django_timezone

from apps.mail.models import ProvisionedMailbox
from apps.mail.services import mail_config
from apps.mail.services.crypto import crypto_service
from apps.mail.services.provisioning import ProvisioningError, get_provisioner

log = logging.getLogger(__name__)


# ── Domain exceptions (порт HTTPException(...) исходника) ──────────────────

class MailboxNotFound(Exception):
    """404 — Mailbox not found."""


class MailboxDomainNotConfigured(Exception):
    """500 — MAILCOW_DOMAIN not configured."""


class MailboxUserConflict(Exception):
    """409 — user_id уже привязан к другому (не удалённому) ящику."""

    def __init__(self, user_id: int, address: str) -> None:
        self.detail = f"User {user_id} already has mailbox {address}"
        super().__init__(self.detail)


class InvalidLocalPart(Exception):
    """400 — local_part после санитайза оказался пустым."""


class MailboxAlreadyDeleted(Exception):
    """409 — update() на уже удалённой строке."""


class MailboxNotActive(Exception):
    """409 — reset_password() на не-active строке."""


class CannotArchive(Exception):
    """409 — archive() из статуса, отличного от active/error."""

    def __init__(self, status: str) -> None:
        self.detail = f"Cannot archive mailbox in status={status}"
        super().__init__(self.detail)


class CannotRestore(Exception):
    """409 — restore() не из archived."""


class CannotDelete(Exception):
    """409 — delete() (stage 2) не из archived."""


class MailboxAddressTaken(Exception):
    """409 — адрес уже занят локальной строкой.

    Возникает только в режиме, где сервер не заводит ящики сам (IMAP): там
    адрес нельзя тихо переименовать в ``i.ivanov2``, он должен совпадать с
    реальным ящиком на сервере.
    """

    def __init__(self, address: str) -> None:
        self.detail = f"Mailbox {address} already exists"
        super().__init__(self.detail)


class MailboxVerificationFailed(Exception):
    """400 — сервер не принял пару адрес/пароль при подключении ящика."""

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(detail)


class MailboxUserSlotTaken(Exception):
    """409 — у пользователя висит УДАЛЁННАЯ строка, а ``user_id`` уникален.

    ``ProvisionedMailbox.user_id`` несёт БЕЗУСЛОВНЫЙ unique — он не исключает
    строки со ``status="deleted"``, поэтому привязать пользователю другой ящик,
    пока старая строка не вычищена, физически нельзя. В ``create()`` это
    исторически вылезает необработанным 500 (задокументировано в
    ``tests/test_mailboxes_api.py``); на новом пути привязки такой же 500 был
    бы просто багом, поэтому здесь он назван вслух.
    """

    def __init__(self, user_id: int, address: str) -> None:
        self.detail = (
            f"У пользователя {user_id} осталась удалённая запись ящика "
            f"{address} — сначала уберите её, затем подключайте новый ящик."
        )
        super().__init__(self.detail)


class RemoteProvisioningFailed(Exception):
    """502 — почтовый сервер отказал.

    Локальная строка при этом уже создана/обновлена и помечена
    ``status="error"`` + ``last_error`` — админ видит её в списке и может
    повторить операцию, а не остаётся с «ничего не произошло».
    """

    def __init__(self, detail: str, mailbox: ProvisionedMailbox | None = None) -> None:
        self.detail = detail
        self.mailbox = mailbox
        super().__init__(detail)


# ── Helpers (буквальный порт) ────────────────────────────────────────────

_TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "shch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}


def _translit(s: str) -> str:
    return "".join(_TRANSLIT.get(c, c) for c in s.lower())


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", _translit(s))


#: как собрать адрес из транслитерированных имени и фамилии
LOCAL_PART_PATTERNS = {
    "first.last": lambda fn, ln: f"{fn}.{ln}",     # sanzhar.inamzhanov
    "f.last": lambda fn, ln: f"{fn[0]}.{ln}",      # s.inamzhanov (историч. дефолт)
    "firstlast": lambda fn, ln: f"{fn}{ln}",       # sanzharinamzhanov
    "first_last": lambda fn, ln: f"{fn}_{ln}",     # sanzhar_inamzhanov
    "flast": lambda fn, ln: f"{fn[0]}{ln}",        # sinamzhanov
    "last.first": lambda fn, ln: f"{ln}.{fn}",     # inamzhanov.sanzhar
    "first": lambda fn, ln: fn,                    # sanzhar
}


def autogen_local_part(first_name: str, last_name: str, pattern: str | None = None) -> str:
    """`Санжар Инамжанов` → `sanzhar.inamzhanov` (шаблон ``first.last``).

    Соглашение об именовании у каждой компании своё, поэтому шаблон —
    настройка (``MAILBOX_LOCAL_PART_PATTERN`` либо поле «Шаблон адреса» в
    интерфейсе), а не константа. Промах здесь особенно дорог в IMAP-режиме:
    адрес обязан совпасть с реальным ящиком на сервере, иначе платформа
    сгенерирует несуществующий и создание просто не пройдёт.

    Дефолт кода — исторический ``f.last`` (``i.ivanov``): менять его глобально
    нельзя, не сломав уже работающие инсталляции.

    Одно из имён пустое → берётся то, что есть (шаблон неприменим); оба
    пустые → ``user``.
    """
    fn = _slug(first_name)
    ln = _slug(last_name)
    if not (fn and ln):
        return fn or ln or "user"

    if pattern is None:
        pattern = mail_config.get_config().local_part_pattern
    build = LOCAL_PART_PATTERNS.get(pattern)
    if build is None:
        log.warning(
            "unknown_local_part_pattern %r — используется f.last; допустимые: %s",
            pattern, ", ".join(LOCAL_PART_PATTERNS),
        )
        build = LOCAL_PART_PATTERNS["f.last"]
    return build(fn, ln)


def generate_password(length: int = 16) -> str:
    """Strong random password — letters, digits, a few symbols.

    Avoids characters that Mailcow's PHP layer or shells may treat oddly
    (`'\"\\`)."""
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*()_-+="
    return "".join(secrets.choice(alphabet) for _ in range(length))


def corporate_local_part(email: str) -> str:
    """Часть до ``@``, если адрес — из корпоративного домена, иначе ``""``.

    Проверка домена обязательна: у пользователя платформы в ``email`` вполне
    может стоять личная почта или адрес другого домена, и делать из неё
    корпоративный ящик нельзя.
    """
    email = (email or "").strip().lower()
    if "@" not in email:
        return ""
    local, _, domain = email.partition("@")
    cfg_domain = (mail_config.get_config().domain or "").strip().lower()
    return local if cfg_domain and domain == cfg_domain else ""


def resolve_local_part(payload) -> str:
    """Адрес до ``@``, каким его получит ящик, БЕЗ подбора свободного номера.

    Вынесено из ``create()``, чтобы сверка (``provision``) считала ровно тот же
    адрес, который создание собиралось занять: посчитай она его хоть немного
    иначе — и проверка «такой ящик уже есть» проверяла бы не тот ящик.

    Порядок источников — от самого явного к догадке:

    1. ``local_part``, введённый руками;
    2. **корпоративный ``email`` пользователя** — админ, вписавший
       ``ruslan.amirov@htq.group``, уже НАЗВАЛ адрес, и подставлять вместо
       него транслитерацию ``r.amirov`` значит завести ящик, не совпадающий
       с логином сотрудника (а заодно промахнуться мимо сверки: искали бы
       один адрес, существует другой);
    3. транслитерация ФИО по настроенному шаблону — когда email не
       корпоративный или его нет вовсе.
    """
    local = (payload.local_part or "").strip().lower()
    if not local:
        local = corporate_local_part(getattr(payload, "email", ""))
    if not local:
        local = autogen_local_part(payload.first_name, payload.last_name)
    # Sanitize whatever was passed — Mailcow accepts a-z0-9._-
    local = re.sub(r"[^a-z0-9._-]+", "", local)
    if not local:
        raise InvalidLocalPart
    return local


def _next_unique_local_part(base: str, domain: str) -> str:
    """Return base, base2, base3, … — first one whose address is unused."""
    candidate = base
    n = 2
    while True:
        address = f"{candidate}@{domain}"
        if not ProvisionedMailbox.objects.filter(address=address).exists():
            return candidate
        candidate = f"{base}{n}"
        n += 1


def awaits_password(mb: ProvisionedMailbox) -> bool:
    """Ящик привязан к сотруднику, но читать его нечем — нужен пароль.

    Это НЕ ошибка и не поломка, а честно названный промежуточный этап. Он
    возникает там, где платформа не может добыть учётку сама:

    * сервер без админ-API (IMAP) — пароль знает только сам сотрудник;
    * Mailcow отказал в app-password (у API-ключа нет прав, сервер ответил
      ошибкой) — автоподключение не вышло, остаётся спросить человека.

    Состояние вычисляется, а не хранится: отдельный ``status`` пришлось бы
    поддерживать в каждом переходе жизненного цикла ящика и он неизбежно
    разошёлся бы с реальностью. Признак же ровно один — есть ли сохранённый
    пароль, — и он всегда под рукой.

    Режим ``none`` исключён намеренно: почтового сервера нет вовсе, читать
    нечего и не откуда, требовать пароль было бы бессмысленной преградой.
    """
    from apps.mail.services.provisioning import resolve_provisioner_name

    if mb.user_id is None or mb.status != "active":
        return False
    if mb.encrypted_smtp_app_password:
        return False
    return resolve_provisioner_name() != "none"


def serialize(mb: ProvisionedMailbox) -> dict:
    """Порт schemas/mailbox.py::MailboxOut."""
    return {
        "id": mb.id,
        "user_id": mb.user_id,
        "local_part": mb.local_part,
        "domain": mb.domain,
        "address": mb.address,
        "status": mb.status,
        "quota_mb": mb.quota_mb,
        "display_name": mb.display_name,
        "last_error": mb.last_error,
        "created_at": mb.created_at.isoformat(),
        "updated_at": mb.updated_at.isoformat(),
        "archived_at": mb.archived_at.isoformat() if mb.archived_at else None,
        "deleted_at": mb.deleted_at.isoformat() if mb.deleted_at else None,
        # Подключён, но пароля нет — почта не пойдёт, пока сотрудник его не
        # введёт. Видно и админу в списке ящиков, и самому сотруднику.
        "awaiting_password": awaits_password(mb),
    }


# ── Reads ────────────────────────────────────────────────────────────────

def list_mailboxes(*, include_deleted: bool = False) -> list[ProvisionedMailbox]:
    qs = ProvisionedMailbox.objects.order_by("-created_at")
    if not include_deleted:
        qs = qs.exclude(status="deleted")
    return list(qs)


def get_by_id(mailbox_id: int) -> ProvisionedMailbox:
    mb = ProvisionedMailbox.objects.filter(id=mailbox_id).first()
    if mb is None:
        raise MailboxNotFound
    return mb


def get_by_user_id(user_id: int) -> ProvisionedMailbox | None:
    return ProvisionedMailbox.objects.filter(user_id=user_id).first()


# ── Writes ───────────────────────────────────────────────────────────────

def store_password(mb: ProvisionedMailbox, password: str) -> None:
    """Сохранить пароль ящика зашифрованным (AES-256-GCM, crypto.py).

    Без этого не работают ни синхронизация писем, ни отправка: и
    ``sync/imap_sync.py``, и ``sender/*_smtp.py`` берут учётку именно отсюда.
    Раньше поле не заполнял никто, из-за чего корпоративная отправка всегда
    падала на «mailcow mailbox has no app-password».
    """
    if not password:
        return
    mb.encrypted_smtp_app_password = crypto_service.encrypt(password)
    mb.save(update_fields=["encrypted_smtp_app_password", "updated_at"])


def stored_password(address: str) -> str | None:
    """Расшифрованный пароль уже заведённого ящика (или None).

    Нужен проверке подключения: админ, проверяющий существующий ящик, не
    должен вводить пароль заново — платформа его уже хранит.
    """
    mb = ProvisionedMailbox.objects.filter(address__iexact=address).first()
    if mb is None or not mb.encrypted_smtp_app_password:
        return None
    try:
        return crypto_service.decrypt(mb.encrypted_smtp_app_password)
    except Exception as exc:  # noqa: BLE001 — вызывающий сообщит «нет пароля»
        log.warning("stored_password_decrypt_failed address=%s: %s", address, exc)
        return None


def mark_error(mb: ProvisionedMailbox, error: str, *, status: str | None = None) -> None:
    mb.last_error = error
    fields = ["last_error", "updated_at"]
    if status is not None and mb.status != status:
        mb.status = status
        fields.append("status")
    mb.save(update_fields=fields)


def _clear_error(mb: ProvisionedMailbox) -> None:
    if mb.last_error:
        mb.last_error = None
        mb.save(update_fields=["last_error", "updated_at"])


def create(payload) -> tuple[ProvisionedMailbox, str | None]:
    """Завести ящик: локальная строка + реальное создание на почтовом сервере.

    Returns (row, generated_password). `generated_password` is None when
    the admin provided one — we never echo back what we received.

    Если сервер отказал, строка остаётся в БД со ``status="error"`` и текстом
    ошибки, а наружу летит ``RemoteProvisioningFailed`` (502) — так админ
    видит и что именно сломалось, и на какой строке, и может повторить.
    """
    cfg = mail_config.get_config()
    domain = cfg.domain
    if not domain:
        raise MailboxDomainNotConfigured

    # Unique-by-user_id: don't let a user end up with two mailboxes.
    if payload.user_id is not None:
        existing = get_by_user_id(payload.user_id)
        if existing and existing.status != "deleted":
            raise MailboxUserConflict(payload.user_id, existing.address)

    provisioner = get_provisioner()

    local = resolve_local_part(payload)
    if getattr(provisioner, "requires_existing_mailbox", False):
        # Адрес обязан совпасть с реальным ящиком на сервере — подставить
        # свободный ``i.ivanov2`` нельзя, это была бы заведомо нерабочая
        # привязка. Занятый адрес здесь честнее вернуть как конфликт.
        if ProvisionedMailbox.objects.filter(address=f"{local}@{domain}").exists():
            raise MailboxAddressTaken(f"{local}@{domain}")
    else:
        # Сервер заведёт ящик под любым адресом (или ящика на сервере нет
        # вовсе) — свободный адрес можно подобрать за админа, как и раньше.
        local = _next_unique_local_part(local, domain)

    password = payload.password or generate_password()
    generated = None if payload.password else password

    quota = payload.quota_mb or cfg.mailcow_default_quota_mb
    full_name = payload.full_name or f"{payload.first_name} {payload.last_name}".strip()
    address = f"{local}@{domain}"

    mb = ProvisionedMailbox.objects.create(
        user_id=payload.user_id,
        local_part=local,
        domain=domain,
        address=address,
        status="active",
        quota_mb=quota,
        display_name=full_name or None,
    )

    try:
        provisioner.create(
            local_part=local, domain=domain, address=address, password=password,
            full_name=full_name, quota_mb=quota,
        )
    except ProvisioningError as exc:
        mark_error(mb, str(exc), status="error")
        raise RemoteProvisioningFailed(str(exc), mb) from exc

    # Пароль пригодится синхронизации и отправке — храним зашифрованным.
    store_password(mb, password)
    _issue_app_password(provisioner, mb, password)
    ensure_account(mb)
    return mb, generated


# ── Подключение УЖЕ существующего ящика ──────────────────────────────────
#
# Единственная реализация «привязать готовый ящик к пользователю». До неё то
# же самое было написано трижды и по-разному: сотрудник сам
# (services/self_service.py), пакетная сверка (reconcile_service._link_orphans)
# и ручной ввод user_id в форме создания. Расхождения были не косметические —
# сверка, например, привязывала ящик, но не добывала ему пароль, и
# «подключён» он оказывался только на бумаге.


def attach_existing(
    *, address: str, user_id: int | None, password: str = "", display_name: str = "",
    quota_mb: int = 0, verify: bool = True,
) -> ProvisionedMailbox:
    """Подключить УЖЕ существующий ящик к пользователю платформы.

    Ящик НЕ создаётся на почтовом сервере — предполагается, что он там уже
    есть (это и выясняет сверка, ``lookup_service``). Функция приводит в
    порядок локальную сторону: строку ``ProvisionedMailbox`` (создаёт или
    переиспользует), сохранённый пароль и ``EmailAccount``, без которого ящик
    не виден ни в разделе «Почта», ни синхронизации, ни отправке.

    ``verify=True`` при непустом пароле → пара проверяется живым логином ДО
    записи: нерабочая привязка хуже её отсутствия, потому что снаружи
    выглядит рабочей. ``verify=False`` — для вызывающих, которые проверили
    сами (``self_service``) или которым проверять нечем (пакетная сверка).
    """
    address = (address or "").strip().lower()
    local_part, _, addr_domain = address.partition("@")
    cfg = mail_config.get_config()

    # ``iexact``, а не точное совпадение: почтовый сервер вправе писать адрес
    # с заглавными (``Petrov@htq.group``), для почты это тот же ящик. Ищи мы
    # побуквенно — рядом со строкой сервера завелась бы её копия в нижнем
    # регистре, и владельца получила бы копия. Найденной строке её написание
    # оставляем как есть: переименовывать ящик сверка не уполномочена.
    existing = ProvisionedMailbox.objects.filter(address__iexact=address).first()
    if (
        existing is not None
        and user_id is not None
        and existing.user_id is not None
        and existing.user_id != user_id
    ):
        raise MailboxAddressTaken(address)

    # user_id уникален безусловно — занятый слот должен стать внятным 409, а
    # не IntegrityError из середины транзакции.
    if user_id is not None:
        blocking = ProvisionedMailbox.objects.filter(user_id=user_id)
        blocking = (blocking.exclude(pk=existing.pk) if existing is not None
                    else blocking.exclude(address__iexact=address))
        blocking = blocking.first()
        if blocking is not None:
            if blocking.status == "deleted":
                raise MailboxUserSlotTaken(user_id, blocking.address)
            raise MailboxUserConflict(user_id, blocking.address)

    if verify and password:
        ok, error = get_provisioner().verify(address=address, password=password)
        if not ok:
            raise MailboxVerificationFailed(
                f"Почтовый сервер не принял эту пару адрес/пароль: {error}"
            )

    with transaction.atomic():
        if existing is None:
            existing = ProvisionedMailbox.objects.create(
                user_id=user_id,
                local_part=local_part,
                domain=addr_domain or cfg.domain,
                address=address,
                status="active",
                quota_mb=quota_mb or cfg.mailcow_default_quota_mb,
                display_name=display_name or None,
            )
        else:
            fields = []
            if user_id is not None and existing.user_id != user_id:
                existing.user_id = user_id
                fields.append("user_id")
            if existing.status != "active":
                existing.status, existing.archived_at = "active", None
                fields += ["status", "archived_at"]
            if display_name and existing.display_name != display_name:
                existing.display_name = display_name
                fields.append("display_name")
            if quota_mb and existing.quota_mb != quota_mb:
                existing.quota_mb = quota_mb
                fields.append("quota_mb")
            if existing.last_error:
                existing.last_error = None
                fields.append("last_error")
            if fields:
                existing.save(update_fields=[*fields, "updated_at"])

        store_password(existing, password)
        ensure_account(existing)

    log.info("mailbox_attached address=%s user_id=%s", address, user_id)
    return existing


def ensure_credentials(mb: ProvisionedMailbox) -> bool:
    """Добыть подключённому ящику рабочий пароль там, где сервер это умеет.

    Ради этого «подключение» и имеет смысл: без сохранённого пароля и
    синхронизация писем, и отправка молча простаивают — обе берут учётку из
    ``encrypted_smtp_app_password``.

    У Mailcow есть отдельные app-password'ы, поэтому платформа выпускает СВОЙ
    и не трогает интерактивный пароль сотрудника: его почтовый клиент и
    телефон продолжают работать как работали. У остальных серверов взять
    пароль неоткуда — возвращается ``False``, и что с этим делать, решает
    вызывающий.
    """
    if stored_password(mb.address):
        return True
    _issue_app_password(get_provisioner(), mb, "")
    return bool(stored_password(mb.address))


def attach_by_email(*, user_id: int, email: str) -> ProvisionedMailbox | None:
    """Подключить пользователю ящик, совпадающий с его корпоративным email.

    Ядро сценария «ящик уже есть — подключить его сам». Ничего НЕ создаёт:
    нет ящика — нет и действия. Возвращает ``None``, когда подключать нечего
    (почта не корпоративная, ящика нет, занят другим сотрудником).

    Найденный ящик привязывается ДАЖЕ ЕСЛИ пароль добыть не удалось — он
    останется ``awaits_password``, и пароль введёт сам сотрудник. Отказаться
    из-за этого от привязки было бы хуже: сотрудник просто не узнал бы, что
    его ящик найден.

    Общее для двух входов — автоматического (``interface`` при создании
    пользователя) и ручного (сотрудник нажал «Подключить» у себя в
    настройках). Разъедься они, «подключить» означало бы разное в
    зависимости от того, кто нажал.
    """
    from apps.mail.services import lookup_service

    if not corporate_local_part(email):
        return None

    found = lookup_service.lookup_candidate(email=email, user_id=user_id)
    if not found.exists or not found.can_attach:
        return None

    mb = attach_existing(address=found.address, user_id=user_id)
    ensure_credentials(mb)
    return mb


def kick_sync(mb: ProvisionedMailbox) -> bool:
    """Забрать письма прямо сейчас, не дожидаясь периодического опроса.

    Ради этого «подключение» и выглядит как подключение: без немедленной
    синхронизации сотрудник видит пустой ящик до минуты и решает, что ничего
    не сработало. Лучший из возможных результат — а не обязательный: письма
    всё равно приедут опросом (``imap_poll_fallback``), поэтому недоступный
    брокер не повод считать подключение неудавшимся.
    """
    from apps.mail.models import EmailAccount

    if not mb.encrypted_smtp_app_password:
        return False  # читать нечем — синхронизировать нечего
    account = EmailAccount.objects.filter(
        user_id=mb.user_id, mailbox_id=mb.id, is_active=True,
    ).first()
    if account is None:
        return False
    try:
        from apps.mail.tasks import incremental_sync_account

        incremental_sync_account.delay(account.id)
    except Exception as exc:  # noqa: BLE001 — брокер недоступен
        log.warning("kick_sync_enqueue_failed account=%s: %s", account.id, exc)
        return False
    return True


# ── Заведение ящика со сверкой ───────────────────────────────────────────


@dataclass(frozen=True)
class ProvisionResult:
    """Что именно произошло по кнопке «Создать ящик».

    ``attached=True`` означает «ящик уже был, мы его подключили» — интерфейс
    обязан сказать это вслух, иначе админ решит, что завёл новый, и пойдёт
    искать его на почтовом сервере.
    """

    mailbox: ProvisionedMailbox
    generated_password: str | None
    attached: bool
    detail: str | None = None
    #: подключён, но ждёт пароль от сотрудника (см. awaits_password)
    awaiting_password: bool = False


def provision(payload) -> ProvisionResult:
    """Завести ящик — но сначала свериться, нет ли такого ящика уже.

    Точка входа для формы «Создать ящик» и для галки «создать ящик» при
    создании пользователя. ``create()`` под ней осталась нетронутой: она
    по-прежнему означает ровно «завести НОВЫЙ ящик», вся новая логика — здесь,
    поверх.

    Существующий ящик подключается, только когда есть КОМУ подключать
    (``user_id``): без владельца «подключение» неотличимо от бездействия, а
    тихо переиспользовать чужую строку опаснее, чем создать ``i.ivanov2``, —
    два однофамильца не должны получить один ящик на двоих. Исключение —
    ящик, найденный ТОЛЬКО на почтовом сервере: там альтернатива подключению
    не ``i.ivanov2``, а отказ mailcow на ``/add/mailbox`` (502), поэтому его
    импортируем и без владельца.
    """
    from apps.mail.services import lookup_service

    cfg = mail_config.get_config()
    if not cfg.domain:
        raise MailboxDomainNotConfigured

    if payload.user_id is not None:
        owned = get_by_user_id(payload.user_id)
        if owned is not None and owned.status != "deleted":
            raise MailboxUserConflict(payload.user_id, owned.address)

    if not getattr(payload, "attach_if_exists", True):
        mb, generated = create(payload)
        return ProvisionResult(mb, generated, attached=False)

    address = f"{resolve_local_part(payload)}@{cfg.domain}"
    found = lookup_service.lookup(address, for_user_id=payload.user_id)
    attachable = found.can_attach and (payload.user_id is not None or found.source == "remote")

    if not attachable:
        # Ящика нет, он принадлежит другому сотруднику, или подключать его
        # некому — во всех трёх случаях поведение прежнее: create() либо
        # заведёт новый (подобрав свободный адрес), либо честно вернёт 409.
        mb, generated = create(payload)
        return ProvisionResult(mb, generated, attached=False)

    password = (getattr(payload, "password", "") or "").strip()
    full_name = payload.full_name or f"{payload.first_name} {payload.last_name}".strip()
    mb = attach_existing(
        address=address,
        user_id=payload.user_id,
        password=password,
        display_name=full_name,
        quota_mb=payload.quota_mb or 0,
    )
    detail = found.detail
    if not ensure_credentials(mb):
        # Автоматом не вышло — значит спрашиваем человека. Ящик привязан и
        # виден сотруднику, но письма пойдут только после того, как он введёт
        # пароль (карточка в профиле, раздел «Почта», баннер после входа).
        log.info("attached_mailbox_awaiting_password address=%s", address)
        detail = (
            f"{found.detail} Платформа не смогла получить доступ к ящику сама — "
            f"сотрудник введёт пароль у себя в профиле."
        )
    return ProvisionResult(
        mb, None, attached=True, detail=detail, awaiting_password=awaits_password(mb),
    )


def account_provider() -> str:
    """Какое значение писать в ``EmailAccount.provider`` для нового ящика.

    Для неподключённого сервера остаётся историческое ``mailcow`` — так
    строки, созданные до подключения корпоративной почты, и строки, созданные
    после, выглядят одинаково, и отправка для них резолвится тем же
    отправителем, что и раньше.
    """
    from apps.mail.services.provisioning import resolve_provisioner_name

    return "imap" if resolve_provisioner_name() == "imap" else "mailcow"


def ensure_account(mb: ProvisionedMailbox):
    """Завести (или переиспользовать) ``EmailAccount`` для выданного ящика.

    Без этой строки ящик существует, но в интерфейсе почты его не видно:
    и список аккаунтов, и синхронизация, и отправка ходят через
    ``EmailAccount``, а создавал корпоративные аккаунты до сих пор никто —
    ящик оставался «мёртвой» строкой в админке.

    Ящик без ``user_id`` (импортированный сверкой, общий ящик вроде
    ``info@``) аккаунта не получает: он никому не принадлежит, показывать его
    некому. Аккаунт появится, когда ящик привяжут к сотруднику.
    """
    from apps.mail.models import AccountType, EmailAccount

    if mb.user_id is None:
        return None

    account = EmailAccount.objects.filter(user_id=mb.user_id, address=mb.address).first()
    if account is not None:
        if account.mailbox_id != mb.id or not account.is_active:
            account.mailbox_id = mb.id
            account.is_active = True
            account.save(update_fields=["mailbox", "is_active", "updated_at"])
        return account

    is_first = not EmailAccount.objects.filter(user_id=mb.user_id).exists()
    return EmailAccount.objects.create(
        user_id=mb.user_id,
        type=AccountType.CORPORATE,
        provider=account_provider(),
        address=mb.address,
        display_name=mb.display_name,
        mailbox=mb,
        # Корпоративный ящик — разумный дефолт для compose, если других нет.
        is_default=is_first,
        is_active=True,
    )


def _issue_app_password(provisioner, mb: ProvisionedMailbox, fallback: str) -> None:
    """Отдельный app-password для IMAP/SMTP там, где сервер это умеет.

    Best-effort: ящик уже создан и рабочий — если сервер не дал app-password,
    синхронизация просто пойдёт под основным паролем, ронять создание из-за
    этого нельзя.
    """
    issue = getattr(provisioner, "issue_app_password", None)
    if issue is None:
        return
    app_password = generate_password(24)
    try:
        issue(address=mb.address, password=app_password)
    except Exception as exc:  # noqa: BLE001 — не критично для создания ящика
        log.warning("app_password_issue_failed address=%s: %s", mb.address, exc)
        return
    store_password(mb, app_password)


def update(mailbox_id: int, payload) -> ProvisionedMailbox:
    mb = get_by_id(mailbox_id)
    if mb.status == "deleted":
        raise MailboxAlreadyDeleted
    changed_fields = []
    if payload.full_name is not None:
        mb.display_name = payload.full_name
        changed_fields.append("display_name")
    if payload.quota_mb is not None and payload.quota_mb != mb.quota_mb:
        mb.quota_mb = payload.quota_mb
        changed_fields.append("quota_mb")
    if changed_fields:
        mb.save(update_fields=[*changed_fields, "updated_at"])
        try:
            get_provisioner().update(
                address=mb.address, full_name=payload.full_name, quota_mb=payload.quota_mb,
            )
        except ProvisioningError as exc:
            # Правка имени/квоты не стоит отказа всего запроса: локальное
            # значение сохранено, расхождение с сервером видно в last_error
            # и попадёт в сверку.
            mark_error(mb, str(exc))
        else:
            _clear_error(mb)
    return mb


def reset_password(mailbox_id: int, payload) -> tuple[ProvisionedMailbox, str | None]:
    mb = get_by_id(mailbox_id)
    if mb.status != "active":
        raise MailboxNotActive
    password = payload.new_password or generate_password()
    generated = None if payload.new_password else password

    try:
        get_provisioner().reset_password(
            address=mb.address, new_password=password,
            force_change=getattr(payload, "force_change", True),
        )
    except ProvisioningError as exc:
        mark_error(mb, str(exc))
        raise RemoteProvisioningFailed(str(exc), mb) from exc

    store_password(mb, password)
    _clear_error(mb)
    return mb, generated


def archive(mailbox_id: int) -> ProvisionedMailbox:
    mb = get_by_id(mailbox_id)
    if mb.status == "archived":
        return mb
    if mb.status not in ("active", "error"):
        raise CannotArchive(mb.status)
    mb.status = "archived"
    mb.archived_at = django_timezone.now()
    mb.save(update_fields=["status", "archived_at", "updated_at"])

    # На сервере архивация = ящик выключен: почта на него больше не ходит,
    # но данные целы (окончательное удаление — вторым этапом, delete()).
    try:
        get_provisioner().set_active(address=mb.address, active=False)
    except ProvisioningError as exc:
        mark_error(mb, str(exc))
    return mb


def restore(mailbox_id: int) -> ProvisionedMailbox:
    mb = get_by_id(mailbox_id)
    if mb.status != "archived":
        raise CannotRestore
    mb.status = "active"
    mb.archived_at = None
    mb.save(update_fields=["status", "archived_at", "updated_at"])

    try:
        get_provisioner().set_active(address=mb.address, active=True)
    except ProvisioningError as exc:
        mark_error(mb, str(exc))
    else:
        _clear_error(mb)
    return mb


def delete(mailbox_id: int) -> None:
    """Stage 2 of the two-step delete — only allowed when archived.

    Локальная строка остаётся как аудит-след (``status="deleted"``), а ящик
    на почтовом сервере удаляется по-настоящему. Отказ сервера не отменяет
    локальное удаление (иначе строка зависла бы в archived навсегда) — он
    пишется в ``last_error`` и всплывёт в сверке.
    """
    mb = get_by_id(mailbox_id)
    if mb.status != "archived":
        raise CannotDelete
    mb.status = "deleted"
    mb.deleted_at = django_timezone.now()
    mb.save(update_fields=["status", "deleted_at", "updated_at"])

    try:
        get_provisioner().delete(address=mb.address)
    except ProvisioningError as exc:
        mark_error(mb, str(exc))


# ── Покрытие: у кого из сотрудников нет рабочей почты ─────────────────────


#: Почему у сотрудника нет рабочей почты. Причина, а не просто «нет ящика»:
#: действия администратора в трёх случаях разные, и без неё список
#: превращается в загадку.
COVERAGE_NO_MAILBOX = "no_mailbox"          # завести ящик
COVERAGE_NOT_LINKED = "not_linked"          # ящик есть, но ничей — свести
COVERAGE_AWAITING_PASSWORD = "awaiting_password"   # спросить пароль у сотрудника


def users_without_mailbox(limit: int = 500) -> list[dict]:
    """Сотрудники с корпоративным адресом, у которых почта не работает.

    Зачем это админу: до сих пор проблема адресовалась сотруднику по одному —
    полосой «введите пароль». Админ не видел ни масштаба, ни того, что часть
    случаев решается им самим за минуту (завести ящик), а не хождением
    сотрудника за паролем.

    Личная почта в список не попадает: делать корпоративный ящик из
    ``@gmail.com`` платформа не умеет и не должна. Уволенные — тоже: ящик им
    больше не нужен.

    Ящик ищется ДВУМЯ путями — по владельцу и по адресу, — потому что это
    разные состояния. Строка, привязанная к сотруднику, означает «почта его»,
    даже если адрес с тех пор сменился; строка с совпадающим адресом, но без
    владельца, означает «ящик на сервере есть, сверка его ещё не связала», и
    заводить второй такой было бы дублем.
    """
    from apps.users import interface as users_interface

    domain = (mail_config.get_config().domain or "").strip().lower()
    if not domain:
        return []

    suffix = f"@{domain}"
    users = [
        u for u in users_interface.list_users_brief(limit=limit)
        if u["is_active"] and (u["email"] or "").strip().lower().endswith(suffix)
    ]
    if not users:
        return []

    live = list(ProvisionedMailbox.objects.exclude(status="deleted"))
    by_address = {mb.address.strip().lower(): mb for mb in live}
    by_user = {mb.user_id: mb for mb in live if mb.user_id is not None}

    out: list[dict] = []
    for user in users:
        email = (user["email"] or "").strip().lower()
        mb = by_user.get(user["id"]) or by_address.get(email)

        if mb is None:
            reason = COVERAGE_NO_MAILBOX
        elif mb.user_id is None:
            reason = COVERAGE_NOT_LINKED
        elif awaits_password(mb):
            reason = COVERAGE_AWAITING_PASSWORD
        else:
            continue        # почта работает — в списке проблем ему не место

        out.append({
            "user_id": user["id"],
            "email": user["email"],
            "full_name": user["full_name"],
            "reason": reason,
            "mailbox_id": mb.id if mb is not None else None,
        })
    return out
