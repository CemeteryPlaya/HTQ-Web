"""Бизнес-логика messenger-core — порт
``services/messenger/app/services/messenger_service.py`` (rooms/messages/
read; Socket.IO-вещание и ``notify_publish`` — Р2, НЕ портируются, см.
докстринг ниже у каждой затронутой функции).

Данные пользователей — ТОЛЬКО через ``apps.users.interface.get_user_brief``/
``get_users_brief`` (Р2: ``chat_user_replicas`` не портируется, см.
``apps/messenger/models.py`` докстринг файла). ``get_users_brief`` отдаёт
``{id, username, email, full_name, is_active}`` — БЕЗ ``first_name``/
``last_name``/``avatar_url``/``is_bot`` (тех полей исходной
``UserReplicaRead`` в реестре ``apps.users`` попросту нет; денормализованный
аватар/бот-флаг появятся вместе с под-задачами attachments/workers, если
будут прокинуты через users.interface или отдельный канал — вне scope
messenger-core). Батчится (``get_users_brief``) там, где сериализуется
больше одного сообщения/участника разом — без N+1.

Вложения (attachments-под-задача, PLAN.md §6.5): ``_serialize_message``
теперь отдаёт РЕАЛЬНЫЙ список ``ChatAttachment`` сообщения (через
``apps.messenger.services.attachment_service.attachments_for_messages`` —
тот же батч-принцип, что ``_briefs_by_id``), и ``send_message`` привязывает
``MessageCreateRequest.attachment_ids`` к созданному сообщению
(``attachment_service.attach_to_message``) — оба места раньше несли
пустую заглушку ``[]``/не принимали ``attachment_ids`` (см. историю этого
файла до attachments-под-задачи).
"""
from __future__ import annotations

import uuid
from typing import Iterable

from django.db import transaction
from django.db.models import Q

from apps.messenger import schemas
from apps.messenger.models import Message, Room, RoomParticipant, RoomParticipantRole, RoomType
from apps.messenger.services import attachment_service
from apps.users import interface as users_interface


class NotAParticipant(Exception):
    """403 — вызывающий/отправитель не участник комнаты. Текст сообщения
    несёт конкретный вызывающий (разный текст на разных путях исходника —
    см. каждый call site)."""


class RoomNotFound(Exception):
    """Комната не найдена. Порт исходника: 404 в rooms.py (get/update_room),
    но 403 в messages.py::send_message (тот же ValueError("Room not found"),
    но роутер send_message ловит его тем же except-блоком, что и
    "not a participant", и всегда отвечает 403) — статус выбирает
    вызывающая вьюха, не это исключение."""


class NotRoomAdmin(Exception):
    """403 — только admin-участник комнаты может её редактировать."""


class NotGroupRoom(Exception):
    """400 — редактирование name/avatar_url разрешено только для group-комнат."""


class InvalidRoomParticipants(Exception):
    """400 — direct-чат обязан иметь ровно двух (различных) участников."""


# ── сериализация ─────────────────────────────────────────────────────────

def _briefs_by_id(user_ids: Iterable[int]) -> dict[int, dict]:
    ids = {uid for uid in user_ids if uid is not None}
    if not ids:
        return {}
    return {b["id"]: b for b in users_interface.get_users_brief(ids)}


def _serialize_participant(rp: RoomParticipant, briefs: dict[int, dict], *, unread_count: int = 0) -> dict:
    return {
        "user_id": rp.user_id,
        "role": rp.role,
        "last_read_message_id": str(rp.last_read_message_id) if rp.last_read_message_id else None,
        "user": briefs.get(rp.user_id),
        "unread_count": unread_count,
    }


def _serialize_message(msg: Message, briefs: dict[int, dict], *, attachments: list[dict] | None = None) -> dict:
    return {
        "id": str(msg.id),
        "room_id": msg.room_id,
        "sender_id": msg.sender_id,
        "content": msg.content,
        "is_encrypted": msg.is_encrypted,
        "is_edited": msg.is_edited,
        "created_at": msg.created_at.isoformat(),
        "sender": briefs.get(msg.sender_id) if msg.sender_id is not None else None,
        # attachments-под-задача: реальный список ChatAttachment этого
        # сообщения. Вызывающий по возможности передаёт предзагруженный
        # батч (``attachments=``, см. list_messages/_last_messages_for
        # ниже) — без него делаем разовый запрос на само сообщение (лишний
        # только для одиночных путей вроде send_message, где батчить нечего).
        "attachments": (
            attachments if attachments is not None
            else attachment_service.attachments_for_messages([msg.id]).get(msg.id, [])
        ),
    }


def _serialize_room(room: Room, *, last_message: dict | None = None,
                     unread_by_user: dict[int, int] | None = None) -> dict:
    participants = list(room.participants.all())
    briefs = _briefs_by_id(p.user_id for p in participants)
    unread_by_user = unread_by_user or {}
    return {
        "id": room.id,
        "storage_key": str(room.storage_key),
        "name": room.name,
        "room_type": room.room_type,
        "is_e2ee": room.is_e2ee,
        "created_at": room.created_at.isoformat(),
        "updated_at": room.updated_at.isoformat() if room.updated_at else None,
        # _refresh_signed_avatar исходника (пере-подписание signed URL) —
        # attachments-под-задача; пока отдаём сырое значение колонки как есть.
        "avatar_url": room.avatar_url,
        "participants": [
            _serialize_participant(p, briefs, unread_count=unread_by_user.get(p.user_id, 0))
            for p in participants
        ],
        "last_message": last_message,
    }


# ── rooms ────────────────────────────────────────────────────────────────

def _find_direct_room(user_ids: set[int]) -> Room | None:
    """Порт ``MessengerService._find_direct_room``: комнаты, где встречаются
    ОБА пользователя, затем проверка, что участников РОВНО эти двое (не
    больше — исключает случайное совпадение с группой)."""
    if len(user_ids) != 2:
        return None
    a, b = tuple(user_ids)
    candidate_ids = (
        Room.objects.filter(room_type=RoomType.DIRECT)
        .filter(id__in=RoomParticipant.objects.filter(user_id=a).values("room_id"))
        .filter(id__in=RoomParticipant.objects.filter(user_id=b).values("room_id"))
        .values_list("id", flat=True)
    )
    for rid in candidate_ids:
        members = set(RoomParticipant.objects.filter(room_id=rid).values_list("user_id", flat=True))
        if members == user_ids:
            return Room.objects.filter(id=rid).first()
    return None


@transaction.atomic
def create_room(creator_id: int, data: schemas.RoomCreateRequest) -> dict:
    """Порт ``create_room``. "Один direct-чат на пару": повторный вызов с той
    же парой возвращает УЖЕ существующую комнату (не дубликат) — и в обоих
    случаях (новая/найденная) роутер отвечает 201 (см. apps/messenger/
    views.py — статус не зависит от ветки, буквально как в исходнике)."""
    participants = set(data.participant_ids)
    participants.add(creator_id)

    if data.room_type == RoomType.DIRECT:
        if len(participants) != 2:
            raise InvalidRoomParticipants("Direct chats must have exactly two participants")
        existing = _find_direct_room(participants)
        if existing is not None:
            return _serialize_room(existing)

    room = Room.objects.create(
        name=data.name, room_type=data.room_type, is_e2ee=data.is_e2ee, avatar_url=data.avatar_url,
    )
    for uid in participants:
        RoomParticipant.objects.create(
            room=room, user_id=uid,
            role=RoomParticipantRole.ADMIN if uid == creator_id else RoomParticipantRole.MEMBER,
        )
    return _serialize_room(room)


def list_rooms(user_id: int) -> list[dict]:
    """Порт ``list_user_rooms``: комнаты, где вызывающий — участник, с
    последним сообщением на комнату и unread_count вызывающего."""
    room_ids = list(RoomParticipant.objects.filter(user_id=user_id).values_list("room_id", flat=True))
    rooms = list(Room.objects.filter(id__in=room_ids))
    ids = [r.id for r in rooms]
    last_messages = _last_messages_for(ids)
    unread = _unread_counts_for(user_id, ids)
    return [
        _serialize_room(r, last_message=last_messages.get(r.id), unread_by_user={user_id: unread.get(r.id, 0)})
        for r in rooms
    ]


def get_room(user_id: int, room_id: int) -> dict:
    """Порт ``get_room``: проверка участия ПЕРЕД проверкой существования
    комнаты (буквальный порядок исходника — не-участник несуществующей
    комнаты тоже получает 403, а не 404)."""
    if not RoomParticipant.objects.filter(room_id=room_id, user_id=user_id).exists():
        raise NotAParticipant("Not a participant")
    room = Room.objects.filter(id=room_id).first()
    if room is None:
        raise RoomNotFound("Room not found")
    return _serialize_room(room)


@transaction.atomic
def update_room(user_id: int, room_id: int, data: schemas.RoomUpdateRequest) -> dict:
    """Порт ``update_room``: только group-комнаты, только admin-участник."""
    rp = RoomParticipant.objects.filter(room_id=room_id, user_id=user_id).first()
    if rp is None:
        raise NotAParticipant("Not a participant")
    if rp.role != RoomParticipantRole.ADMIN:
        raise NotRoomAdmin("Only room admins can edit")

    room = Room.objects.filter(id=room_id).first()
    if room is None:
        raise RoomNotFound("Room not found")
    if room.room_type != RoomType.GROUP:
        raise NotGroupRoom("Only group rooms support name/avatar editing")

    if data.name is not None:
        room.name = data.name.strip() or None
    if data.avatar_url is not None:
        room.avatar_url = data.avatar_url.strip() or None
    room.save(update_fields=["name", "avatar_url", "updated_at"])
    return _serialize_room(room)


def _last_messages_for(room_ids: list[int]) -> dict[int, dict]:
    """Порт ``_attach_last_messages``: последнее сообщение на комнату,
    одним запросом (Postgres ``DISTINCT ON`` через ``.distinct("room_id")``,
    требует совпадающий ведущий ``order_by``)."""
    if not room_ids:
        return {}
    msgs = list(
        Message.objects.filter(room_id__in=room_ids)
        .order_by("room_id", "-created_at")
        .distinct("room_id")
    )
    briefs = _briefs_by_id(m.sender_id for m in msgs)
    atts = attachment_service.attachments_for_messages([m.id for m in msgs])
    return {m.room_id: _serialize_message(m, briefs, attachments=atts.get(m.id, [])) for m in msgs}


def _unread_counts_for(user_id: int, room_ids: list[int]) -> dict[int, int]:
    """Порт ``_unread_counts_for``: непрочитанные = сообщения комнаты НЕ от
    вызывающего, созданные ПОСЛЕ его ``last_read_message_id`` (или все такие
    сообщения, если ничего ещё не прочитано).

    Реализовано проще, чем self-join исходника (по комнате отдельным
    запросом вместо одного общего), с тем же наблюдаемым результатом —
    оправдано тем, что список комнат пользователя мал (Р2/messenger-core
    scope не включает оптимизацию под большие объёмы)."""
    if not room_ids:
        return {}
    participants = {
        rp.room_id: rp.last_read_message_id
        for rp in RoomParticipant.objects.filter(user_id=user_id, room_id__in=room_ids)
    }
    last_read_ids = [v for v in participants.values() if v is not None]
    last_read_created_at = dict(
        Message.objects.filter(id__in=last_read_ids).values_list("id", "created_at")
    )
    counts: dict[int, int] = {}
    for room_id, last_read_id in participants.items():
        qs = Message.objects.filter(room_id=room_id).exclude(sender_id=user_id)
        if last_read_id is not None:
            threshold = last_read_created_at.get(last_read_id)
            if threshold is None:
                # last_read_message_id не резолвится ни в одно сообщение —
                # то же поведение, что LEFT JOIN исходника с NULL created_at
                # (сравнение с NULL никогда не true) -> 0 непрочитанных.
                counts[room_id] = 0
                continue
            qs = qs.filter(created_at__gt=threshold)
        counts[room_id] = qs.count()
    return counts


# ── messages ─────────────────────────────────────────────────────────────

@transaction.atomic
def send_message(sender_id: int, data: schemas.MessageCreateRequest) -> dict:
    """Порт ``send_message``. Socket.IO-вещание (``message_new`` в комнату и
    в персональные каналы участников) и ``notify_publish``-событие
    (``CHANNEL_NEW_CHAT_MESSAGE``) — Р2, НЕ портируются (см. бриф п.6:
    Socket.IO — отдельная под-задача).

    ``attachment_ids`` (attachments-под-задача): привязка через
    ``attachment_service.attach_to_message`` — её исключения (комната/
    отправитель не совпадают, уже прикреплено к другому сообщению)
    пробрасываются как есть; вызывающая вьюха ловит ИМЕННО их, наравне с
    ``NotAParticipant``/``RoomNotFound`` — исходник заворачивает все три
    случая в один и тот же ``except ValueError`` и ВСЕГДА отвечает 403 (см.
    apps/messenger/views.py::send_message)."""
    if not RoomParticipant.objects.filter(room_id=data.room_id, user_id=sender_id).exists():
        raise NotAParticipant("Sender is not a participant in this room")
    room = Room.objects.filter(id=data.room_id).first()
    if room is None:
        raise RoomNotFound("Room not found")

    msg = Message.objects.create(
        room=room, sender_id=sender_id, content=data.content,
        is_encrypted=data.is_encrypted, metadata_json=data.metadata_json,
    )
    attachment_service.attach_to_message(
        msg, attachment_ids=data.attachment_ids, room_id=data.room_id, sender_id=sender_id,
    )
    return _serialize_message(msg, _briefs_by_id([sender_id]))


def list_messages(room_id: int, *, q: str | None = None, since=None, until=None,
                   data_type: str | None = None, limit: int = 50, offset: int = 0) -> list[dict]:
    """Порт ``list_messages``. ``q`` — ``ILIKE`` по содержимому ИЛИ по имени
    файла любого вложения сообщения (``exists()``-подзапрос исходника ->
    ``Q(attachments__filename__icontains=...)`` + ``.distinct()`` здесь, чтобы
    JOIN не размножал строки при >1 совпавшем вложении). ``data_type`` —
    сообщения, несущие хотя бы одно вложение этого вида (та же логика)."""
    qs = Message.objects.filter(room_id=room_id).order_by("-created_at")
    needs_distinct = False
    if q:
        pattern = q.strip()
        qs = qs.filter(Q(content__icontains=pattern) | Q(attachments__filename__icontains=pattern))
        needs_distinct = True
    if since is not None:
        qs = qs.filter(created_at__gte=since)
    if until is not None:
        qs = qs.filter(created_at__lt=until)
    if data_type:
        qs = qs.filter(attachments__data_type=data_type)
        needs_distinct = True
    if needs_distinct:
        qs = qs.distinct()
    msgs = list(qs[offset:offset + limit])
    briefs = _briefs_by_id(m.sender_id for m in msgs)
    atts = attachment_service.attachments_for_messages([m.id for m in msgs])
    return [_serialize_message(m, briefs, attachments=atts.get(m.id, [])) for m in msgs]


def mark_read(user_id: int, room_id: int, message_id: uuid.UUID) -> None:
    """Порт ``MessengerService.mark_read`` (достижимая ветка — см.
    ``messages.py::mark_message_read``; ``read.py``'s дубликат мёртв, см.
    ``apps/messenger/models.py::AuditLog`` докстринг). Socket.IO
    ``message_read``-вещание — Р2, НЕ портируется."""
    rp = RoomParticipant.objects.filter(room_id=room_id, user_id=user_id).first()
    if rp is None:
        raise NotAParticipant("User not in room")
    rp.last_read_message_id = message_id
    rp.save(update_fields=["last_read_message_id", "updated_at"])
