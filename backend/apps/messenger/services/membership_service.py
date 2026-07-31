"""Управление составом группового чата: пригласить, исключить, сменить роль.

До этого сервиса состав группы фиксировался в момент создания
(``messenger_service.create_room``) НАВСЕГДА: ни одного эндпойнта, который
добавил бы или убрал участника, в messenger не было — ни в этом порте, ни в
FastAPI-исходнике. Выход из группы появился вместе с ``room_lifecycle``
(DELETE /rooms/{id}), а этот модуль закрывает остальное.

Правила (продуктовое решение, источника нет):

* только ``room_type == "group"`` — состав личного чата неизменяем по
  определению;
* любое действие доступно только участнику с ролью ``admin`` этой комнаты;
* последнего админа нельзя ни исключить, ни разжаловать — группа без
  владельца стала бы неуправляемой (и неудаляемой, см. room_lifecycle);
* себя этим API не трогают: выход из группы — ``DELETE /rooms/{id}``
  (там же корректно обрабатывается скрытие), а не самоисключение здесь.

Аудит: каждое действие — строка в ``messenger_auditlog`` (тот же приём и та
же таблица, что ``room_lifecycle``): у администратора платформы остаётся
история, кто кого приглашал/исключал, даже когда участника в комнате давно
нет. Именно поэтому исключение УДАЛЯЕТ строку ``RoomParticipant`` (доступ
должен пропасть немедленно — на участии завязаны send_message/get_room/
выдача вложений), а история членства остаётся в аудите.

Реалтайм: после каждого действия — ``realtime.room_updated`` в персональные
каналы затронутых (свежедобавленный ещё не подписан на канал комнаты, см.
``realtime.py``).
"""
from __future__ import annotations

import logging

from django.db import transaction

from apps.messenger.models import Room, RoomParticipant, RoomParticipantRole, RoomType
from apps.messenger.models import AuditLog
from apps.messenger.services import realtime, room_lifecycle
from apps.users import interface as users_interface

logger = logging.getLogger(__name__)


class NotAParticipant(Exception):
    """403 — вызывающий не участник комнаты."""


class NotRoomAdmin(Exception):
    """403 — действие доступно только админу комнаты."""


class RoomNotFound(Exception):
    """404 — комнаты нет (или она удалена владельцем)."""


class NotGroupRoom(Exception):
    """400 — состав можно менять только у группового чата."""


class InvalidParticipants(Exception):
    """400 — пустой список, неизвестные пользователи, попытка тронуть себя."""


class LastAdmin(Exception):
    """400 — последнего админа группы нельзя исключить/разжаловать."""


def _require_group_admin(actor_id: int, room_id: int) -> Room:
    """Общий гейт всех трёх операций; порядок проверок — как в
    ``messenger_service.get_room``/``update_room`` (участие раньше
    существования)."""
    rp = RoomParticipant.objects.filter(room_id=room_id, user_id=actor_id).first()
    if rp is None:
        raise NotAParticipant("Not a participant")
    if rp.role != RoomParticipantRole.ADMIN:
        raise NotRoomAdmin("Only room admins can manage participants")

    room = Room.objects.filter(id=room_id).first()
    if room is None or room_lifecycle.is_deleted(room_id):
        raise RoomNotFound("Room not found")
    if room.room_type != RoomType.GROUP:
        raise NotGroupRoom("Only group rooms support membership changes")
    return room


def _record(request, *, actor_id: int, action: str, room_id: int, changes: dict) -> None:
    """Как ``room_lifecycle._record``: здесь строка аудита — обязательная
    часть операции (история членства живёт ТОЛЬКО в ней), поэтому сбой не
    глотается — вся транзакция откатывается вместе с изменением состава."""
    AuditLog.objects.create(
        user_id=actor_id,
        action=action,
        resource_type="Room",
        resource_id=str(room_id),
        changes=changes,
        ip_address=request.META.get("REMOTE_ADDR") if request is not None else None,
        user_agent=request.headers.get("user-agent") if request is not None else None,
    )


def _participant_ids(room_id: int) -> list[int]:
    return list(RoomParticipant.objects.filter(room_id=room_id).values_list("user_id", flat=True))


@transaction.atomic
def add_participants(request, actor_id: int, room_id: int, user_ids: list[int]) -> list[int]:
    """Пригласить в группу. Возвращает id реально добавленных (уже состоящие
    в группе молча пропускаются — повторное приглашение не ошибка)."""
    _require_group_admin(actor_id, room_id)

    wanted = {int(u) for u in user_ids if u is not None}
    wanted.discard(actor_id)
    if not wanted:
        raise InvalidParticipants("No users to add")

    known = {b["id"] for b in users_interface.get_users_brief(wanted)}
    unknown = wanted - known
    if unknown:
        raise InvalidParticipants(f"Unknown users: {sorted(unknown)}")

    existing = set(_participant_ids(room_id))
    to_add = sorted(wanted - existing)
    for uid in to_add:
        RoomParticipant.objects.create(
            room_id=room_id, user_id=uid, role=RoomParticipantRole.MEMBER,
        )
    if to_add:
        _record(request, actor_id=actor_id, action="participant_added",
                room_id=room_id, changes={"added": to_add})
        transaction.on_commit(
            lambda: realtime.room_updated(room_id, existing | set(to_add))
        )
        logger.info("messenger participants added: room=%s by=%s users=%s", room_id, actor_id, to_add)
    return to_add


@transaction.atomic
def remove_participant(request, actor_id: int, room_id: int, target_id: int) -> None:
    """Исключить из группы. Доступ пропадает немедленно (строка участия
    удаляется), история — в аудите."""
    _require_group_admin(actor_id, room_id)
    if target_id == actor_id:
        raise InvalidParticipants("Use DELETE /rooms/{id} to leave the group")

    target = RoomParticipant.objects.filter(room_id=room_id, user_id=target_id).first()
    if target is None:
        raise InvalidParticipants("User is not a participant")
    if target.role == RoomParticipantRole.ADMIN:
        admins = RoomParticipant.objects.filter(
            room_id=room_id, role=RoomParticipantRole.ADMIN,
        ).count()
        if admins <= 1:
            raise LastAdmin("Cannot remove the last admin of the group")

    target.delete()
    _record(request, actor_id=actor_id, action="participant_removed",
            room_id=room_id, changes={"removed": target_id, "role": target.role})
    remaining = set(_participant_ids(room_id))
    transaction.on_commit(
        lambda: realtime.room_updated(room_id, remaining | {target_id})
    )
    logger.info("messenger participant removed: room=%s by=%s user=%s", room_id, actor_id, target_id)


@transaction.atomic
def set_role(request, actor_id: int, room_id: int, target_id: int, role: str) -> None:
    """Назначить/снять админа группы."""
    _require_group_admin(actor_id, room_id)
    if role not in (RoomParticipantRole.ADMIN, RoomParticipantRole.MEMBER):
        raise InvalidParticipants(f"Unknown role: {role}")

    target = RoomParticipant.objects.filter(room_id=room_id, user_id=target_id).first()
    if target is None:
        raise InvalidParticipants("User is not a participant")
    if target.role == role:
        return  # идемпотентно

    if (target.role == RoomParticipantRole.ADMIN and role == RoomParticipantRole.MEMBER):
        admins = RoomParticipant.objects.filter(
            room_id=room_id, role=RoomParticipantRole.ADMIN,
        ).count()
        if admins <= 1:
            raise LastAdmin("Cannot demote the last admin of the group")

    old_role = target.role
    target.role = role
    target.save(update_fields=["role", "updated_at"])
    _record(request, actor_id=actor_id, action="participant_role_changed",
            room_id=room_id, changes={"user_id": target_id, "from": old_role, "to": role})
    participants = set(_participant_ids(room_id))
    transaction.on_commit(lambda: realtime.room_updated(room_id, participants))
    logger.info("messenger role changed: room=%s by=%s user=%s %s->%s",
                room_id, actor_id, target_id, old_role, role)
