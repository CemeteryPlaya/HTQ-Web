"""Публичный API аппки mail для ДРУГИХ аппок (контракт PLAN.md §7).

Производитель: Поток A (фаза mail, PLAN.md §6.4 — под-задача webhooks+
workers, последняя в домене mail). Потребитель: apps.users — каскад
деактивации пользователя (SUSPENDED → архивация почтовых ящиков). Вызов из
users добавляется на интеграции (PLAN.md §8, call-site в apps.users НЕ
трогается здесь). Прямой импорт apps.mail.* из другой аппки запрещён
(test_app_isolation.py) — это единственная разрешённая дверь.

Реализация — порт каскада ``services/email/app/workers/user_events.py``
(``CHANNEL_DEACTIVATED`` ветка ``_handle``): та функция подписывалась на
Redis pub/sub канал ``user.deactivated``, публикуемый user-service. Redis
pub/sub НЕ портируется в этот Django-монолит (Р2 — тот же класс решений, что
и ``notify_publish``/``sync/mapper.py``'s docstring) — эта interface-функция
СТАЛА подписчиком: users вызывает её напрямую (обычный Python-вызов вместо
pub/sub), тот же наблюдаемый эффект.

Функция начинается с require_service("mail").
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from htqweb.fallback import fallback

from apps.core.services import ServiceDisabled, require_service
from apps.mail.models import AccountType, EmailAccount, ProvisionedMailbox
from apps.mail.services import mailbox_service as mbx_svc

log = logging.getLogger(__name__)


def archive_user_mailboxes(user_id: int) -> None:
    """Archive every mailbox owned by ``user_id`` (personal + corporate).

    Port of ``user_events.py``'s ``_archive_personal_accounts`` +
    ``_archive_corporate_mailbox`` (``CHANNEL_DEACTIVATED`` path only — the
    30-day purge-clock stamping done on ``CHANNEL_DELETED`` is a distinct
    lifecycle event, not part of this interface function's contract, and
    ``final_purge_archived_mailboxes`` (``apps/mail/tasks.py``) already reaps
    anything archived past ``MAILBOX_PURGE_AFTER_DAYS`` regardless of how it
    got archived).

    * Personal (OAuth) ``EmailAccount`` rows → ``is_active=False`` (pauses
      their sync; the row is kept so re-activation is one PATCH away, same
      as the source).
    * The corporate ``ProvisionedMailbox`` (at most one per ``user_id`` —
      ``unique=True`` on that column) → archived via
      ``mailbox_service.archive()`` (already-tested local status transition;
      does NOT call ``MailcowClient`` — Р2/seam, see that module's
      docstring). ``CannotArchive`` is swallowed: a mailbox that is already
      ``archived``/``deleted``/``error`` needs no action here, mirroring the
      source's ``status == "active"`` filter (nothing to do outside that
      state).
    """
    require_service("mail")

    EmailAccount.objects.filter(
        user_id=user_id, type=AccountType.PERSONAL, is_active=True,
    ).update(is_active=False)

    mb = ProvisionedMailbox.objects.filter(user_id=user_id, status="active").first()
    if mb is not None:
        try:
            mbx_svc.archive(mb.id)
        except mbx_svc.CannotArchive:
            pass


# ── Провижининг ящика при создании пользователя ───────────────────────────


@dataclass(frozen=True)
class _MailboxRequest:
    """Форма, которую ждёт ``mailbox_service.create``.

    Отдельный лёгкий объект вместо ``schemas.MailboxCreateRequest``: аппка
    users не должна знать про pydantic-схемы соседа, а сервису достаточно
    утиной типизации по этим полям.
    """

    user_id: int | None = None
    local_part: str = ""
    #: email пользователя платформы; если он в корпоративном домене, он же и
    #: есть адрес ящика (см. mailbox_service.resolve_local_part)
    email: str = ""
    first_name: str = ""
    last_name: str = ""
    full_name: str = ""
    password: str = ""
    quota_mb: int = 0
    must_change_password: bool = True
    #: найденный ящик подключить к пользователю, а не заводить дубль
    attach_if_exists: bool = True


def provision_mailbox(
    *, user_id: int, first_name: str = "", last_name: str = "", full_name: str = "",
    local_part: str = "", email: str = "", password: str = "", quota_mb: int = 0,
) -> tuple[dict | None, str | None]:
    """Завести корпоративный ящик для пользователя платформы.

    Потребитель — ``apps.users.services.admin_service.create_user``: галочка
    «создать почтовый ящик» в форме создания пользователя раньше принималась
    и молча игнорировалась (S2S-вызов в удалённый email-сервис), из-за чего
    админ получал ``mailbox_error`` вместо ящика.

    Идёт через ``provision``, а не ``create``: если корпоративный ящик с этим
    адресом уже заведён (почтовым администратором мимо платформы или прошлым
    прогоном), он ПОДКЛЮЧАЕТСЯ новому пользователю, а не дублируется. Флаг
    ``attached`` в ответе говорит, что именно произошло.

    Возвращает ``(mailbox_dict | None, error | None)`` и НИКОГДА не бросает:
    неудачное создание ящика не должно откатывать уже созданного
    пользователя — админ увидит текст ошибки и заведёт ящик отдельно из
    раздела «Корпоративные ящики». Отключённая аппка mail — тоже штатный
    случай (а не 503 на весь запрос создания пользователя): в отличие от
    остальных функций этого модуля, ``ServiceDisabled`` здесь ловится и
    превращается в тот же ``error``.
    """
    try:
        require_service("mail")
    except ServiceDisabled as exc:
        return None, f"Почтовый модуль отключён: {exc.message}"

    payload = _MailboxRequest(
        user_id=user_id, local_part=local_part, email=email, first_name=first_name,
        last_name=last_name, full_name=full_name, password=password, quota_mb=quota_mb,
    )
    try:
        result = mbx_svc.provision(payload)
    except mbx_svc.MailboxDomainNotConfigured:
        return None, (
            "Домен корпоративной почты не настроен (MAILCOW_DOMAIN / "
            "CORPORATE_MAIL_DOMAIN) — ящик не создан."
        )
    except mbx_svc.MailboxUserConflict as exc:
        return None, exc.detail
    except mbx_svc.MailboxUserSlotTaken as exc:
        return None, exc.detail
    except mbx_svc.MailboxAddressTaken as exc:
        return None, exc.detail
    except mbx_svc.MailboxVerificationFailed as exc:
        return None, exc.detail
    except mbx_svc.InvalidLocalPart:
        return None, "Некорректный адрес ящика (local_part)"
    except mbx_svc.RemoteProvisioningFailed as exc:
        # Строка создана и помечена error — отдаём её вместе с ошибкой, чтобы
        # админ видел, какой именно ящик чинить.
        payload_out = mbx_svc.serialize(exc.mailbox) if exc.mailbox is not None else None
        return payload_out, exc.detail
    except Exception as exc:  # noqa: BLE001 — создание пользователя важнее
        # Все ОЖИДАЕМЫЕ отказы разобраны ветками выше и возвращают внятный
        # текст. Сюда попадает то, чего мы не предвидели, — и именно поэтому
        # подмена громкая: пользователь создан, ящика нет, а причина известна
        # одному этому логу.
        fallback("mail.provision.unexpected_failure", None,
                 reason="создание почтового ящика упало непредвиденно; "
                        "пользователь всё равно создан",
                 exc=exc, user_id=user_id)
        return None, f"Не удалось создать ящик: {exc}"

    return {
        **mbx_svc.serialize(result.mailbox),
        "generated_password": result.generated_password,
        # «Подключён существующий» и «создан новый» — разные новости для
        # админа: во втором случае он выдаёт сотруднику пароль, в первом —
        # ничего не выдаёт, ящик работает как работал.
        "attached": result.attached,
        "detail": result.detail,
    }, None


def attach_mailbox_by_email(*, user_id: int, email: str) -> dict | None:
    """Подключить пользователю корпоративный ящик, совпадающий с его email.

    Сценарий: сотрудника заводят на платформе с адресом
    ``ruslan.amirov@htq.group``, а такой ящик на почтовом сервере уже есть —
    его завёл почтовый администратор. Отдельной команды «подключить» человеку
    давать не нужно: платформа сама сверяет адрес и привязывает найденный ящик.

    Отличие от ``provision_mailbox`` — эта функция **ничего не создаёт**. Её
    зовут, когда ящик не заказывали: нет ящика — нет и действия. Поэтому она
    молчалива и возвращает ``None`` в большинстве случаев:

    * email не из корпоративного домена (личная почта, другой домен);
    * ящика с таким адресом нет ни в платформе, ни на почтовом сервере;
    * ящик занят другим сотрудником.

    Найденный ящик подключается ДАЖЕ ЕСЛИ пароль добыть не удалось (сервер без
    админ-API, Mailcow отказал в app-password): он остаётся привязанным и
    помечается ``awaiting_password``, а пароль вводит сам сотрудник. Отменить
    из-за этого привязку было бы хуже — сотрудник просто не узнал бы, что его
    ящик найден.

    НИКОГДА не бросает: неудача подключения ящика не должна ронять создание
    пользователя — это две независимые операции, и вторая важнее.
    """
    try:
        require_service("mail")
    except ServiceDisabled:
        return None

    try:
        # Проверка домена — до всего остального: у пользователя платформы в
        # email вполне может стоять личная почта, корпоративным ящиком она не
        # становится.
        if not mbx_svc.corporate_local_part(email):
            return None

        from apps.mail.services import lookup_service

        # lookup_candidate сам соберёт адрес тем же кодом, что и создание, —
        # домен здесь знать не нужно.
        found = lookup_service.lookup_candidate(email=email, user_id=user_id)
        if not found.exists or not found.can_attach:
            return None

        # Пароль здесь не спрашиваем и подключение из-за него не отменяем:
        # если платформа не сможет добыть учётку сама, ящик останется
        # привязанным и «ждущим», а пароль введёт сам сотрудник. Отказаться
        # от привязки было бы хуже — сотрудник вообще не узнал бы, что его
        # ящик найден.
        mb = mbx_svc.attach_existing(address=found.address, user_id=user_id)
        mbx_svc.ensure_credentials(mb)
    except Exception as exc:  # noqa: BLE001 — пользователь важнее ящика
        # Громко: снаружи «ящик не подключился» неотличимо от «ящика не было»,
        # и без этой записи причину не узнает никто.
        fallback("mail.attach_by_email.failed", None,
                 reason="автоподключение корпоративного ящика по email упало; "
                        "пользователь всё равно создан",
                 exc=exc, user_id=user_id)
        return None

    log.info("mailbox_auto_attached user_id=%s address=%s awaiting_password=%s",
             user_id, found.address, mbx_svc.awaits_password(mb))
    return {**mbx_svc.serialize(mb), "attached": True, "detail": found.detail}


def get_user_mailbox(user_id: int) -> dict | None:
    """Ящик пользователя (или None) — для карточек/профиля."""
    require_service("mail")
    mb = ProvisionedMailbox.objects.filter(user_id=user_id).exclude(status="deleted").first()
    return mbx_svc.serialize(mb) if mb is not None else None
