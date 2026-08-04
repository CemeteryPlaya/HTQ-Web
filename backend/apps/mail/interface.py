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
    first_name: str = ""
    last_name: str = ""
    full_name: str = ""
    password: str = ""
    quota_mb: int = 0
    must_change_password: bool = True


def provision_mailbox(
    *, user_id: int, first_name: str = "", last_name: str = "", full_name: str = "",
    local_part: str = "", password: str = "", quota_mb: int = 0,
) -> tuple[dict | None, str | None]:
    """Завести корпоративный ящик для пользователя платформы.

    Потребитель — ``apps.users.services.admin_service.create_user``: галочка
    «создать почтовый ящик» в форме создания пользователя раньше принималась
    и молча игнорировалась (S2S-вызов в удалённый email-сервис), из-за чего
    админ получал ``mailbox_error`` вместо ящика.

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
        user_id=user_id, local_part=local_part, first_name=first_name,
        last_name=last_name, full_name=full_name, password=password, quota_mb=quota_mb,
    )
    try:
        mb, generated_password = mbx_svc.create(payload)
    except mbx_svc.MailboxDomainNotConfigured:
        return None, (
            "Домен корпоративной почты не настроен (MAILCOW_DOMAIN / "
            "CORPORATE_MAIL_DOMAIN) — ящик не создан."
        )
    except mbx_svc.MailboxUserConflict as exc:
        return None, exc.detail
    except mbx_svc.MailboxAddressTaken as exc:
        return None, exc.detail
    except mbx_svc.InvalidLocalPart:
        return None, "Некорректный адрес ящика (local_part)"
    except mbx_svc.RemoteProvisioningFailed as exc:
        # Строка создана и помечена error — отдаём её вместе с ошибкой, чтобы
        # админ видел, какой именно ящик чинить.
        payload_out = mbx_svc.serialize(exc.mailbox) if exc.mailbox is not None else None
        return payload_out, exc.detail
    except Exception as exc:  # noqa: BLE001 — создание пользователя важнее
        log.exception("provision_mailbox_failed user_id=%s", user_id)
        return None, f"Не удалось создать ящик: {exc}"

    return {**mbx_svc.serialize(mb), "generated_password": generated_password}, None


def get_user_mailbox(user_id: int) -> dict | None:
    """Ящик пользователя (или None) — для карточек/профиля."""
    require_service("mail")
    mb = ProvisionedMailbox.objects.filter(user_id=user_id).exclude(status="deleted").first()
    return mbx_svc.serialize(mb) if mb is not None else None
