"""HTTP-вьюхи домена messenger — ``/api/messenger/v1/{rooms,messages}/*``.

Порт ``services/messenger/app/api/v1/{rooms,messages,read}.py``
(messenger-core под-задача). Вьюхи тонкие: аутентификация, парсинг, коды
ответа. Логика — в ``apps/messenger/services/messenger_service.py``.

Авторизация: ВСЕ 8 эндпойнтов — обычный залогиненный пользователь
(``get_current_user`` исходника) -> ``api_view(auth="jwt")``. Никакого
``admin=True`` эндпойнта в messenger-core нет (в отличие от apps.mail
mailboxes/*) — участие в комнате (``RoomParticipant``) сужает видимость,
СТРОГИЙ participant-scoping воспроизведён от исходника буквально, включая
порядок проверок (см. ``messenger_service.py``).

8, а не 9 достижимых роутов (бриф считает 9 = rooms 4 + messages 4 + read 1
как функции исходника в 3 файлах): ``services/messenger/app/api/v1/read.py``
регистрирует ТОТ ЖЕ итоговый путь/метод, что и
``messages.py::mark_message_read`` (см. ``app/main.py`` — ``messages_router``
на ``prefix=".../messages"`` с путём ``"/room/{room_id}/read/{message_id}"``;
``read_router`` на ``prefix=".../v1"`` с путём
``"/messages/room/{room_id}/read/{message_id}"`` — идентичный итоговый URL),
причём ПОСЛЕ него -> ``read.py::mark_read`` никогда не вызывается в реальном
сервисе (Starlette матчит первый зарегистрированный роут). ``mark_message_read``
ниже воспроизводит РЕАЛЬНО достижимую ветку (``messages.py``); подробности —
``apps/messenger/models.py::AuditLog`` докстринг.
"""
from __future__ import annotations

import datetime
import uuid

from django.http import HttpResponse

from htqweb.http import api_view, json_error

from . import schemas
from .models import RoomParticipant
from .services import messenger_service as msg_svc

_VALID_DATA_TYPES = ("images", "audio", "documents", "video")


class _QueryValidationError(Exception):
    """422 — некорректный query-параметр (порт неявной FastAPI
    ``Query(..., ge=..., le=...)``/``Literal``/``datetime`` валидации из
    ``messages.py::list_messages``). Тот же приём, что
    ``apps/mail/views.py::_QueryValidationError``."""


def _int_query(request, name: str, *, default: int, ge: int | None = None,
               le: int | None = None) -> int:
    raw = request.GET.get(name)
    if raw is None or raw == "":
        value = default
    else:
        try:
            value = int(raw)
        except ValueError:
            raise _QueryValidationError(name) from None
    if (ge is not None and value < ge) or (le is not None and value > le):
        raise _QueryValidationError(name)
    return value


def _datetime_query(request, name: str) -> datetime.datetime | None:
    raw = request.GET.get(name)
    if raw is None or raw == "":
        return None
    try:
        return datetime.datetime.fromisoformat(raw)
    except ValueError:
        raise _QueryValidationError(name) from None


# ── /rooms/ (rooms.py, 4 эндпойнта) ────────────────────────────────────────

@api_view(methods=("GET",), auth="jwt")
def _list_rooms(request):
    return msg_svc.list_rooms(request.token.user_id)


@api_view(methods=("POST",), auth="jwt", body=schemas.RoomCreateRequest, status=201)
def _create_room(request, data: schemas.RoomCreateRequest):
    try:
        return msg_svc.create_room(request.token.user_id, data)
    except msg_svc.InvalidRoomParticipants as exc:
        return json_error(str(exc), 400)


def rooms_collection(request):
    if request.method == "GET":
        return _list_rooms(request)
    if request.method == "POST":
        return _create_room(request)
    return json_error("Method Not Allowed", 405)


@api_view(methods=("GET",), auth="jwt")
def _get_room(request, room_id: int):
    try:
        return msg_svc.get_room(request.token.user_id, room_id)
    except msg_svc.NotAParticipant as exc:
        return json_error(str(exc), 403)
    except msg_svc.RoomNotFound as exc:
        return json_error(str(exc), 404)


@api_view(methods=("PATCH",), auth="jwt", body=schemas.RoomUpdateRequest)
def _update_room(request, room_id: int, data: schemas.RoomUpdateRequest):
    try:
        return msg_svc.update_room(request.token.user_id, room_id, data)
    except msg_svc.NotAParticipant as exc:
        return json_error(str(exc), 403)
    except msg_svc.NotRoomAdmin as exc:
        return json_error(str(exc), 403)
    except msg_svc.RoomNotFound as exc:
        return json_error(str(exc), 404)
    except msg_svc.NotGroupRoom as exc:
        return json_error(str(exc), 400)


def room_detail(request, room_id: int):
    if request.method == "GET":
        return _get_room(request, room_id=room_id)
    if request.method == "PATCH":
        return _update_room(request, room_id=room_id)
    return json_error("Method Not Allowed", 405)


# ── /messages/* (messages.py, 4 эндпойнта — 4-й, mark_message_read,
# поглощает read.py::mark_read, см. докстринг модуля выше) ─────────────────

@api_view(methods=("POST",), auth="jwt", body=schemas.MessageCreateRequest, status=201)
def send_message(request, data: schemas.MessageCreateRequest):
    try:
        return msg_svc.send_message(request.token.user_id, data)
    except (msg_svc.NotAParticipant, msg_svc.RoomNotFound) as exc:
        # Исходник: оба случая — ValueError, роутер ловит ОДНИМ except-блоком
        # и всегда отвечает 403 (не 404, в отличие от get_room/update_room).
        return json_error(str(exc), 403)


@api_view(methods=("GET",), auth="jwt")
def list_messages(request, room_id: int):
    if not RoomParticipant.objects.filter(room_id=room_id, user_id=request.token.user_id).exists():
        return json_error("Not a participant", 403)

    try:
        limit = _int_query(request, "limit", default=50, ge=1, le=100)
        offset = _int_query(request, "offset", default=0, ge=0)
        since = _datetime_query(request, "since")
        until = _datetime_query(request, "until")
    except _QueryValidationError as exc:
        return json_error(f"Invalid query parameter: {exc}", 422)

    q = request.GET.get("q") or None
    data_type = request.GET.get("data_type") or None
    if data_type is not None:
        if data_type not in _VALID_DATA_TYPES:
            return json_error("Invalid query parameter: data_type", 422)
        # ChatAttachment (attachments-под-задача) не портирован — ни одно
        # сообщение сейчас не несёт вложений, поэтому фильтр по data_type
        # честно не находит ничего до той под-задачи (см. messenger_service.py
        # докстринг list_messages).
        return []

    return msg_svc.list_messages(room_id, q=q, since=since, until=until, limit=limit, offset=offset)


@api_view(methods=("POST",), auth="jwt")
def mark_message_read(request, room_id: int, message_id: uuid.UUID):
    try:
        msg_svc.mark_read(request.token.user_id, room_id, message_id)
    except msg_svc.NotAParticipant as exc:
        return json_error(str(exc), 403)
    return HttpResponse(status=204)


@api_view(methods=("POST",), auth="jwt")
def publish_typing(request, room_id: int):
    """Порт ``messages.py::publish_typing``. Socket.IO-вещание
    (``user_typing``) — Р2/Socket.IO-под-задача, НЕ портируется здесь, см.
    бриф п.6. Исходник НЕ проверяет членство вызывающего в комнате перед
    вещанием (буквальная странность source — не усиливаем, не ослабляем);
    сейчас, без Socket.IO, эндпойнт существует только для паритета путей
    фронта/контракта и всегда отвечает 204 без побочных эффектов."""
    return HttpResponse(status=204)
