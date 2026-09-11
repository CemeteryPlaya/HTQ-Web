"""Ссылки-приглашения в видеоконференцию.

Отвечает на один вопрос: как позвать человека в звонок ссылкой — и коллегу,
и внешнего участника, у которого учётки в платформе нет.

До этого позвать можно было только идентификатором комнаты: сотрудник
открывал ``/room/<id>`` и входил под своей учёткой, а посторонний не входил
никак — маршрут комнаты требует авторизации, а SFU принимает лишь
платформенный токен.

Устройство. Приглашение — отдельная сущность (``ConferenceInvite``), а не
просто адрес комнаты, и это даёт три вещи, которых у голого ``/room/<id>``
нет: ссылку можно **отозвать**, у неё есть **срок**, и по токену в ней
нельзя догадаться о других комнатах.

Гостевой вход устроен в два шага и намеренно:

1. ``resolve`` — публичная проверка ссылки. Отдаёт только то, что нужно
   странице входа: название встречи и можно ли войти гостем. Комнату не
   выдаёт: до ввода имени человек ещё не участник.
2. ``issue_guest_access`` — выдача гостевого JWT под конкретную комнату
   (``htqweb.authn.jwt.issue_guest_token``). Токен не пускает никуда, кроме
   SFU, и только в ту комнату, на которую выписан.

Разделение важно: если бы ``resolve`` сразу отдавал токен, любой сканер
ссылок (антивирус в почте, предпросмотр в мессенджере) выжигал бы лимит
входов и «занимал» встречу, просто открыв URL.
"""
from __future__ import annotations

import logging
import secrets
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from apps.cms.models import ConferenceInvite
from htqweb.authn.jwt import issue_guest_token

log = logging.getLogger(__name__)

#: Длина токена в ссылке. 32 hex-символа = 128 бит энтропии: перебором не
#: берётся, а ссылка остаётся достаточно короткой, чтобы не ломать письма.
TOKEN_BYTES = 16

#: Единственные языки, которые реально понимает фронт (`frontend/src/i18n.js`,
#: `supportedLngs: ['en', 'ru']`). Список сознательно короткий и живёт здесь,
#: а не в модели: это бизнес-правило («что показываем»), а не ограничение
#: хранения.
SUPPORTED_LOCALES = frozenset({"ru", "en"})


def normalize_locale(value: str | None) -> str:
    """Привести язык к тому, что умеет фронт, либо к «не задано».

    Неизвестное значение (опечатка, будущий язык, ручная правка в БД) не
    должно ронять страницу входа — оно ведёт себя ровно как отсутствующее:
    гость увидит язык, который определит его браузер, как это было до этой
    функциональности.

    Без подчёркивания и экспортируется намеренно: единственная публичная
    ручка, отдающая ``locale`` до входа (``conference_invite_public`` в
    ``views.py``, ``auth=None``), берёт значение отсюда же, а не читает
    ``invite.locale`` напрямую — иначе ручная правка в БД дошла бы до
    гостя, минуя нормализацию, которая есть везде, кроме неё.
    """
    normalized = (value or "").strip().lower()
    return normalized if normalized in SUPPORTED_LOCALES else ""


class InviteInvalid(Exception):
    """Ссылка не работает. ``code`` объясняет почему — его показывает страница
    входа, поэтому формулировки человеческие, а не отладочные."""

    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(detail)


def build_join_url(invite: ConferenceInvite, *, base_url: str = "") -> str:
    """Адрес, который человек получит в письме или сообщении.

    ``base_url`` приходит из запроса, когда ссылку собирает браузерный
    сценарий, и из ``PUBLIC_BASE_URL`` — когда письмо отправляет фоновая
    задача, у которой origin взять неоткуда.
    """
    root = (base_url or settings.PUBLIC_BASE_URL or "").rstrip("/")
    return f"{root}/join/{invite.token}"


def create_invite(*, room_id: str, created_by_id: int | None, title: str = "",
                  allow_guests: bool = True, ttl_hours: int | None = None,
                  max_uses: int = 0, locale: str = "") -> ConferenceInvite:
    room = (room_id or "").strip()
    if not room:
        raise InviteInvalid("room_required", "Не указана комната")

    hours = ttl_hours or settings.CONFERENCE_INVITE_TTL_HOURS
    invite = ConferenceInvite.objects.create(
        room_id=room,
        token=secrets.token_hex(TOKEN_BYTES),
        title=(title or "").strip()[:255],
        created_by_id=created_by_id,
        allow_guests=allow_guests,
        expires_at=timezone.now() + timedelta(hours=hours),
        max_uses=max(0, int(max_uses or 0)),
        locale=normalize_locale(locale),
    )
    log.info("conference_invite_created room=%s by=%s guests=%s",
             room, created_by_id, allow_guests)
    return invite


def resolve(token: str) -> ConferenceInvite:
    """Найти живое приглашение или объяснить, почему оно не живое."""
    invite = ConferenceInvite.objects.filter(token=(token or "").strip()).first()
    if invite is None:
        raise InviteInvalid("not_found", "Ссылка недействительна")
    if invite.revoked_at is not None:
        raise InviteInvalid("revoked", "Организатор отозвал эту ссылку")
    if invite.expires_at <= timezone.now():
        raise InviteInvalid("expired", "Срок действия ссылки истёк")
    if invite.max_uses and invite.uses >= invite.max_uses:
        raise InviteInvalid("exhausted", "По этой ссылке уже вошли все, кого ждали")
    return invite


def issue_guest_access(invite: ConferenceInvite, *, display_name: str) -> dict:
    """Выдать гостю токен на комнату этого приглашения.

    Счётчик входов растёт через ``F()`` — два человека, открывшие ссылку
    одновременно, иначе затёрли бы инкремент друг друга, и лимит входов стал
    бы условностью.
    """
    if not invite.allow_guests:
        raise InviteInvalid(
            "guests_not_allowed",
            "По этой ссылке входят только сотрудники — войдите в платформу",
        )

    name = (display_name or "").strip()[:80]
    if not name:
        raise InviteInvalid("name_required", "Представьтесь, чтобы войти")

    token, ttl_seconds = issue_guest_token(room_id=invite.room_id, display_name=name)

    with transaction.atomic():
        ConferenceInvite.objects.filter(pk=invite.pk).update(
            uses=F("uses") + 1, last_used_at=timezone.now())

    log.info("conference_guest_joined room=%s invite=%s name=%r",
             invite.room_id, invite.id, name)
    return {
        "access_token": token,
        "expires_in": ttl_seconds,
        "room_id": invite.room_id,
        "display_name": name,
        "title": invite.title,
        # Гость окажется в комнате уже после этого ответа — фронт кладёт
        # значение в guestSession и держит язык переключённым внутри звонка,
        # без него интерфейс откатился бы на язык браузера при входе в комнату.
        "locale": normalize_locale(invite.locale),
    }


def revoke(invite_id: int) -> ConferenceInvite:
    invite = ConferenceInvite.objects.filter(pk=invite_id).first()
    if invite is None:
        raise InviteInvalid("not_found", "Приглашение не найдено")
    if invite.revoked_at is None:
        invite.revoked_at = timezone.now()
        invite.save(update_fields=["revoked_at"])
    return invite


def list_for_room(room_id: str) -> list[ConferenceInvite]:
    return list(ConferenceInvite.objects.filter(room_id=(room_id or "").strip()))


def serialize(invite: ConferenceInvite, *, base_url: str = "") -> dict:
    return {
        "id": invite.id,
        "room_id": invite.room_id,
        "title": invite.title,
        "url": build_join_url(invite, base_url=base_url),
        "token": invite.token,
        "allow_guests": invite.allow_guests,
        "expires_at": invite.expires_at,
        "revoked": invite.revoked_at is not None,
        "max_uses": invite.max_uses,
        "uses": invite.uses,
        "locale": normalize_locale(invite.locale),
        "created_at": invite.created_at,
    }


def send_invite(invite: ConferenceInvite, *, emails: list[str], user_ids: list[int],
                sender_name: str = "", base_url: str = "") -> dict:
    """Разослать ссылку почтой и уведомлением в мессенджер.

    Best-effort по каждому каналу отдельно: недоступный SMTP не должен
    отменять доставку тем, кого зовут через мессенджер, и наоборот. Отчёт
    возвращается вызывающему — организатор должен видеть, кому дошло, а не
    гадать по молчанию.

    Почта отправляется штатным ``django.core.mail``, а НЕ через ``apps.mail``
    — и это осознанно: тот отправляет письма от имени конкретного почтового
    ящика сотрудника и требует его учётных данных, а приглашение идёт от
    платформы. Тот же механизм уже используется в ``apps.cms.tasks`` для
    уведомлений админам.
    """
    from django.core.mail import send_mail

    url = build_join_url(invite, base_url=base_url)
    subject = invite.title or "Приглашение в видеоконференцию"
    who = f"{sender_name} приглашает вас" if sender_name else "Вас приглашают"
    lines = [f"{who} в видеоконференцию."]
    if invite.title:
        lines.append(invite.title)
    lines.append(f"\nСсылка для входа: {url}")
    body = "\n".join(lines) + "\n"

    report = {"emails_sent": 0, "notified": 0, "errors": []}

    clean_emails = [value.strip() for value in emails if value and value.strip()]
    if clean_emails:
        try:
            send_mail(subject, body, None, clean_emails, fail_silently=False)
            report["emails_sent"] = len(clean_emails)
        except Exception as exc:  # noqa: BLE001 — канал независим от остальных
            log.warning("conference_invite_email_failed invite=%s: %s", invite.id, exc)
            report["errors"].append(f"Почта: {exc}")

    if user_ids:
        try:
            from apps.messenger import interface as messenger

            messenger.dispatch_notification(list(user_ids), {
                "type": "conference_invite",
                "title": subject,
                "url": url,
                "room_id": invite.room_id,
                "from": sender_name,
            })
            report["notified"] = len(user_ids)
        except Exception as exc:  # noqa: BLE001 — см. выше
            log.warning("conference_invite_notify_failed invite=%s: %s", invite.id, exc)
            report["errors"].append(f"Мессенджер: {exc}")

    return report
