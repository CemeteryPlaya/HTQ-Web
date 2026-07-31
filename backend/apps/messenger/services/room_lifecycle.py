"""Удаление/скрытие комнат мессенджера — без физического удаления строк.

Требования, из которых вырос этот модуль:

* владелец ГРУППОВОГО чата удаляет чат целиком, для всех участников;
* личный чат на двоих удалить нельзя — можно только убрать из своего списка;
* у администратора платформы остаётся аудит и полная история ВСЕХ чатов —
  с сообщениями и файлами — даже у удалённых.

Третий пункт исключает ``Room.objects.delete()``: FK у ``Message`` и
``ChatAttachment`` стоят на ``CASCADE`` (apps/messenger/models.py), так что
физическое удаление комнаты унесло бы с собой ровно то, что администратор
обязан продолжать видеть.

Значит нужен soft-delete. Обычно это колонка ``deleted_at`` — но менять схему
БД в этом проекте нельзя, поэтому состояние хранится СОБЫТИЯМИ в уже
существующей таблице ``messenger_auditlog`` (``apps.messenger.models
.AuditLog``). Таблица заведена при портировании ради паритета схемы и до сих
пор не имела ни одного писателя (см. её докстринг: единственный писатель
источника был недостижим), а нужные колонки уже проиндексированы
(``action``, ``resource_id``, ``user_id``) — то есть это не «склад для
костыля», а ровно то хранилище, для которого таблица и предназначалась:
аудит действий над комнатами. Аудит, которого требует п.3, получается не
довеском, а самим механизмом.

Модель событий (``resource_type="Room"``, ``resource_id=str(room_id)``):

``room_deleted``  — комната удалена владельцем группы. Действует на ВСЕХ:
                    комната исчезает из ``list_rooms`` у каждого участника.
                    Обратного события нет — удаление окончательно (для
                    пользователей; администратор видит всё).
``room_hidden``   — комната убрана из списка ОДНОГО пользователя
                    (``user_id`` события). Личный чат и выход участника из
                    группы. Отменяется САМА, если после момента скрытия в
                    комнате появилось новое сообщение (поведение Telegram —
                    «убрал, но собеседник написал»).
``room_unhidden`` — пользователь сам вернул чат: нажал на собеседника в
                    списке контактов, и ``create_room`` отдал уже
                    существующую личную комнату вместо новой. Без этого
                    события чат открылся бы, но в списке остался бы скрытым
                    до первого сообщения. Сравнивается по времени с
                    ``room_hidden``: показываем, если последнее событие —
                    ``unhidden``.

Что НЕ делается намеренно: ``RoomParticipant`` при скрытии/удалении не
трогается. Иначе пользователь потерял бы доступ к комнате (``mark_read``,
``send_message``, выдача вложений — всё проверяет участие), а история для
администратора лишилась бы состава участников.
"""
from __future__ import annotations

import datetime
import logging

from django.db.models import Max

from apps.messenger.models import AuditLog, Message, Room, RoomParticipant, RoomParticipantRole, RoomType

logger = logging.getLogger(__name__)

ACTION_DELETED = "room_deleted"
ACTION_HIDDEN = "room_hidden"
ACTION_UNHIDDEN = "room_unhidden"
RESOURCE_TYPE = "Room"


class NotAParticipant(Exception):
    """403 — вызывающий не участник комнаты."""


class RoomNotFound(Exception):
    """404 — комнаты нет."""


class AlreadyDeleted(Exception):
    """404 — комната уже удалена владельцем; повторное удаление бессмысленно."""


# ── чтение состояния ──────────────────────────────────────────────────────

def deleted_room_ids(room_ids: list[int] | None = None) -> set[int]:
    """Комнаты, удалённые владельцем (для всех). ``room_ids=None`` — по всей
    таблице (используется админ-выдачей, где комнат немного)."""
    qs = AuditLog.objects.filter(action=ACTION_DELETED, resource_type=RESOURCE_TYPE)
    if room_ids is not None:
        if not room_ids:
            return set()
        qs = qs.filter(resource_id__in=[str(r) for r in room_ids])
    out: set[int] = set()
    for raw in qs.values_list("resource_id", flat=True):
        try:
            out.add(int(raw))
        except (TypeError, ValueError):
            # Чужая/битая строка аудита не должна ронять выдачу списка чатов.
            continue
    return out


def _latest_by_room(user_id: int, action: str, room_ids: list[int]) -> dict[int, datetime.datetime]:
    """``{room_id: время последнего такого события у этого пользователя}``."""
    rows = (
        AuditLog.objects
        .filter(action=action, resource_type=RESOURCE_TYPE,
                user_id=user_id, resource_id__in=[str(r) for r in room_ids])
        .values("resource_id")
        .annotate(at=Max("created_at"))
    )
    out: dict[int, datetime.datetime] = {}
    for row in rows:
        try:
            out[int(row["resource_id"])] = row["at"]
        except (TypeError, ValueError):
            continue
    return out


def hidden_at_for_user(user_id: int, room_ids: list[int]) -> dict[int, datetime.datetime]:
    """``{room_id: когда пользователь убрал чат}`` — только те комнаты, где
    последнее его действие именно СКРЫТИЕ (пользователь мог убирать и
    возвращать чат не один раз; ``room_unhidden`` позже ``room_hidden``
    означает, что чат снова показан)."""
    if not room_ids:
        return {}
    hidden = _latest_by_room(user_id, ACTION_HIDDEN, room_ids)
    if not hidden:
        return {}
    unhidden = _latest_by_room(user_id, ACTION_UNHIDDEN, list(hidden))
    return {
        rid: at for rid, at in hidden.items()
        if rid not in unhidden or unhidden[rid] < at
    }


def unhide_room(user_id: int, room_id: int) -> None:
    """Вернуть чат в список пользователя. Пишется только если он реально
    скрыт — иначе в аудите копились бы пустые события на каждый клик по
    контакту."""
    if not hidden_at_for_user(user_id, [room_id]):
        return
    AuditLog.objects.create(
        user_id=user_id, action=ACTION_UNHIDDEN,
        resource_type=RESOURCE_TYPE, resource_id=str(room_id),
    )
    logger.info("messenger room_unhidden: room_id=%s by=%s", room_id, user_id)


def is_deleted(room_id: int) -> bool:
    """Удалена ли комната владельцем — точечная проверка для путей записи
    (``send_message``) и чтения одной комнаты (``get_room``)."""
    return bool(deleted_room_ids([room_id]))


def visible_room_ids(user_id: int, room_ids: list[int]) -> list[int]:
    """Фильтр для ``list_rooms``: убирает удалённые владельцем комнаты и те,
    что пользователь убрал сам — если только после скрытия туда не написали.

    Порядок ``room_ids`` сохраняется."""
    if not room_ids:
        return []

    deleted = deleted_room_ids(room_ids)
    hidden = hidden_at_for_user(user_id, room_ids)

    last_message_at: dict[int, datetime.datetime] = {}
    if hidden:
        last_message_at = {
            row["room_id"]: row["at"]
            for row in Message.objects.filter(room_id__in=list(hidden))
            .values("room_id").annotate(at=Max("created_at"))
        }

    visible = []
    for rid in room_ids:
        if rid in deleted:
            continue
        hidden_at = hidden.get(rid)
        if hidden_at is not None:
            newest = last_message_at.get(rid)
            if newest is None or newest <= hidden_at:
                continue  # с момента скрытия ничего нового — оставляем скрытым
        visible.append(rid)
    return visible


# ── запись ────────────────────────────────────────────────────────────────

def _record(request, *, user_id: int, action: str, room: Room, changes: dict) -> None:
    """Та же неубиваемая семантика, что у ``apps.cms.services.audit
    .record_action``: аудит не имеет права уронить уже выполненный запрос.

    ВАЖНОЕ отличие от cms: здесь строка аудита — не побочная запись, а САМО
    состояние (см. докстринг модуля), поэтому исключение не глотается, а
    пробрасывается — иначе пользователь получил бы 204 на «удаление»,
    которого не произошло."""
    ip = request.META.get("REMOTE_ADDR") if request is not None else None
    user_agent = request.headers.get("user-agent") if request is not None else None
    AuditLog.objects.create(
        user_id=user_id,
        action=action,
        resource_type=RESOURCE_TYPE,
        resource_id=str(room.id),
        changes=changes,
        ip_address=ip,
        user_agent=user_agent,
        correlation_id=getattr(request, "request_id", None) if request is not None else None,
    )


def delete_or_hide_room(request, user_id: int, room_id: int) -> str:
    """Единая ручка ``DELETE /rooms/{id}``. Возвращает, что именно произошло:
    ``"deleted"`` (групповой чат снесён владельцем для всех) или ``"hidden"``
    (чат убран из списка вызывающего).

    Порядок проверок — как у ``get_room``/``update_room`` в
    ``messenger_service``: сначала участие, потом существование комнаты (не
    участник несуществующей комнаты получает 403, а не 404)."""
    rp = RoomParticipant.objects.filter(room_id=room_id, user_id=user_id).first()
    if rp is None:
        raise NotAParticipant("Not a participant")

    room = Room.objects.filter(id=room_id).first()
    if room is None:
        raise RoomNotFound("Room not found")
    if room_id in deleted_room_ids([room_id]):
        raise AlreadyDeleted("Room not found")

    is_group_owner = (
        room.room_type == RoomType.GROUP and rp.role == RoomParticipantRole.ADMIN
    )

    if is_group_owner:
        participants = list(
            RoomParticipant.objects.filter(room_id=room_id).values_list("user_id", flat=True)
        )
        _record(request, user_id=user_id, action=ACTION_DELETED, room=room, changes={
            "room_type": room.room_type,
            "name": room.name,
            "participants": participants,
            "messages": Message.objects.filter(room_id=room_id).count(),
        })
        logger.info("messenger room_deleted: room_id=%s by=%s", room_id, user_id)
        return "deleted"

    # Личный чат — удалить нельзя ни одной из сторон; участник группы (не
    # владелец) выходит из неё тем же событием.
    _record(request, user_id=user_id, action=ACTION_HIDDEN, room=room, changes={
        "room_type": room.room_type,
        "reason": "left_group" if room.room_type == RoomType.GROUP else "hidden_direct",
    })
    logger.info("messenger room_hidden: room_id=%s by=%s", room_id, user_id)
    return "hidden"


# ── админ-выдача ──────────────────────────────────────────────────────────

def deletion_records(room_ids: list[int]) -> dict[int, dict]:
    """``{room_id: {...}}`` по событиям удаления — для админ-эндпойнтов,
    чтобы удалённая комната была видна КАК удалённая, а не молча как обычная.
    Сообщения и вложения при этом никуда не делись: админ-выдача их не
    фильтрует (см. apps/messenger/views.py::admin_list_room_messages)."""
    if not room_ids:
        return {}
    rows = (
        AuditLog.objects
        .filter(action=ACTION_DELETED, resource_type=RESOURCE_TYPE,
                resource_id__in=[str(r) for r in room_ids])
        .order_by("-created_at")
        .values("resource_id", "user_id", "created_at")
    )
    out: dict[int, dict] = {}
    for row in rows:
        try:
            rid = int(row["resource_id"])
        except (TypeError, ValueError):
            continue
        out.setdefault(rid, {"deleted_at": row["created_at"].isoformat(),
                             "deleted_by": row["user_id"]})
    return out
