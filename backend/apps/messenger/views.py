"""HTTP-вьюхи домена messenger —
``/api/messenger/v1/{rooms,messages,attachments,keys}/*``.

Порт ``services/messenger/app/api/v1/{rooms,messages,read,attachments,
keys}.py``. Вьюхи тонкие: аутентификация, парсинг, коды ответа. Логика — в
``apps/messenger/services/{messenger_service,attachment_service,
key_service}.py``.

Авторизация: 11 из 13 эндпойнтов ниже — обычный залогиненный пользователь
(``get_current_user`` исходника) -> ``api_view(auth="jwt")``. Единственное
исключение — ``GET /attachments/file/{id}``/``.../thumb`` (``get_optional_user``
исходника: браузер не может передать ``Authorization`` внутри ``<img src>``,
поэтому JWT опционален, а sig/exp — обязательный публичный контракт; см.
``serve_attachment``/``serve_attachment_thumb`` ниже). Никакого ``admin=True``
эндпойнта в messenger нет — участие в комнате (``RoomParticipant``) сужает
видимость, СТРОГИЙ participant-scoping воспроизведён от исходника буквально,
включая порядок проверок (см. ``messenger_service.py``/``attachment_service.py``).

8, а не 9 достижимых rooms/messages-роутов (бриф считает 9 = rooms 4 +
messages 4 + read 1 как функции исходника в 3 файлах): ``services/messenger/
app/api/v1/read.py`` регистрирует ТОТ ЖЕ итоговый путь/метод, что и
``messages.py::mark_message_read`` (см. ``app/main.py`` — ``messages_router``
на ``prefix=".../messages"`` с путём ``"/room/{room_id}/read/{message_id}"``;
``read_router`` на ``prefix=".../v1"`` с путём
``"/messages/room/{room_id}/read/{message_id}"`` — идентичный итоговый URL),
причём ПОСЛЕ него -> ``read.py::mark_read`` никогда не вызывается в реальном
сервисе (Starlette матчит первый зарегистрированный роут). ``mark_message_read``
ниже воспроизводит РЕАЛЬНО достижимую ветку (``messages.py``); подробности —
``apps/messenger/models.py::AuditLog`` докстринг.

Плюс 5 эндпойнтов attachments-под-задачи (PLAN.md §6.5): ``attachments.py``
(``upload_attachment``/``serve_attachment``/``serve_attachment_thumb``) +
``keys.py`` (``upload_keys``/``get_user_keys``).

Плюс workers/admin под-задача (PLAN.md §6.5, последняя под-задача messenger):
``admin.py`` (3 эндпойнта, ``require_admin`` исходника -> ``api_view(auth=
"jwt", admin=True)``), ``users.py`` (4 регистрации роутов — ``me``×2 +
``search``×2, Р2 у обоих — см. докстринги секций ниже).

``internal.py`` (S2S ``/internal/bot-message``, общий секрет
``X-Internal-Token``) и ``users.py::ingest_user_replica`` (``/users/ingest``)
снесены — P1.2/P1.3 audit-спеки (2026-07-22, ``docs/superpowers/plans/
2026-07-22-django-native-audit-spec.md``): ``ChatUserReplica`` в Django нет
(приёмник был без цели), а S2S-эндпойнт не имел ни одного in-process
потребителя после cutover (grep по backend/frontend/sfu пуст — единственный
вызывающий был HTTP-путь из ``system_bots_service.post_bot_message``,
которая по-прежнему достижима из ``apps.messenger.tasks.dispatch_bot_message``
напрямую, без HTTP).
"""
from __future__ import annotations

import datetime
import uuid

from django.http import HttpResponse, HttpResponseRedirect

from htqweb.http import _authenticate_jwt, api_view, json_error

from apps.users import interface as users_interface

from . import schemas
from .models import Message, Room, RoomParticipant
from .services import attachment_service, key_service
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
    except (
        msg_svc.NotAParticipant, msg_svc.RoomNotFound,
        attachment_service.AttachmentsNotAvailable, attachment_service.AttachmentAlreadyAttached,
    ) as exc:
        # Исходник: все четыре случая — ValueError, роутер ловит ОДНИМ
        # except-блоком и всегда отвечает 403 (не 404/400, в отличие от
        # get_room/update_room) — включая обе attachment_ids-ошибки
        # (attachments-под-задача, см. ``MessengerService.send_message``).
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
    if data_type is not None and data_type not in _VALID_DATA_TYPES:
        return json_error("Invalid query parameter: data_type", 422)

    return msg_svc.list_messages(
        room_id, q=q, since=since, until=until, data_type=data_type, limit=limit, offset=offset,
    )


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


# ── /attachments/* (attachments.py, 3 эндпойнта) ────────────────────────────

@api_view(methods=("POST",), auth="jwt", status=201)
def upload_attachment(request):
    """Порт ``attachments.py::upload_attachment`` (multipart/form-data:
    ``room_id`` + ``file``)."""
    try:
        room_id = int(request.POST.get("room_id", ""))
    except (TypeError, ValueError):
        return json_error({"room_id": "field required"}, 422)

    upload = request.FILES.get("file")
    if upload is None:
        return json_error({"file": "field required"}, 422)

    try:
        attachment = attachment_service.upload_attachment(
            request.token.user_id, room_id=room_id, upload=upload,
        )
    except attachment_service.NotAParticipant as exc:
        return json_error(str(exc), 403)
    except attachment_service.RoomNotFound as exc:
        return json_error(str(exc), 404)
    except attachment_service.AttachmentUploadRejected as exc:
        return json_error(exc.detail, exc.status_code)
    return attachment_service.serialize_attachment(attachment)


def _sig_exp_from_query(request) -> tuple[str, int] | None:
    """``sig``/``exp`` — обязательные query-параметры у исходника
    (``Query(...)``/``Query(..., )`` типа ``int``) -> FastAPI 422 при
    отсутствии/нечисловом ``exp``. ``None`` здесь означает "422"."""
    sig = request.GET.get("sig")
    exp_raw = request.GET.get("exp")
    if not sig or exp_raw is None:
        return None
    try:
        return sig, int(exp_raw)
    except ValueError:
        return None


@api_view(methods=("GET",), auth=None)
def serve_attachment(request, attachment_id: uuid.UUID):
    """Порт ``attachments.py::serve_attachment``. ``auth=None`` +
    ``_authenticate_jwt`` вручную воспроизводит ``get_optional_user``
    исходника (``htqweb.http.api_view`` несёт только "обязательный jwt"/
    "без auth" — тот же приём, что ``apps/media_files/views.py::
    download_file``)."""
    parsed = _sig_exp_from_query(request)
    if parsed is None:
        return json_error("Invalid query parameter: sig/exp required", 422)
    sig, exp = parsed

    user = _authenticate_jwt(request)
    try:
        url = attachment_service.resolve_attachment_redirect(
            attachment_id, sig, exp, user.user_id if user is not None else None,
        )
    except attachment_service.InvalidSignature as exc:
        return json_error(str(exc), 403)
    except attachment_service.NotAParticipant as exc:
        return json_error(str(exc), 403)
    except attachment_service.AttachmentNotFound as exc:
        return json_error(str(exc), 404)
    return HttpResponseRedirect(url)


@api_view(methods=("GET",), auth=None)
def serve_attachment_thumb(request, attachment_id: uuid.UUID):
    """Порт ``attachments.py::serve_attachment_thumb`` — тот же flow, редирект
    на превью (или на оригинал, если ``thumbnail_path`` NULL)."""
    parsed = _sig_exp_from_query(request)
    if parsed is None:
        return json_error("Invalid query parameter: sig/exp required", 422)
    sig, exp = parsed

    user = _authenticate_jwt(request)
    try:
        url = attachment_service.resolve_attachment_thumb_redirect(
            attachment_id, sig, exp, user.user_id if user is not None else None,
        )
    except attachment_service.InvalidSignature as exc:
        return json_error(str(exc), 403)
    except attachment_service.NotAParticipant as exc:
        return json_error(str(exc), 403)
    except attachment_service.AttachmentNotFound as exc:
        return json_error(str(exc), 404)
    return HttpResponseRedirect(url)


# ── /keys/* (keys.py, 2 эндпойнта) ──────────────────────────────────────────

@api_view(methods=("POST",), auth="jwt", body=schemas.UserKeyUploadRequest, status=201)
def upload_keys(request, data: schemas.UserKeyUploadRequest):
    """Порт ``keys.py::upload_keys``."""
    key = key_service.upsert_key(
        request.token.user_id, device_id=data.device_id,
        public_identity_key=data.public_identity_key,
        signed_pre_key=data.signed_pre_key, signature=data.signature,
    )
    return key_service.serialize_key(key)


@api_view(methods=("GET",), auth="jwt")
def get_user_keys(request, user_id: int):
    """Порт ``keys.py::get_user_keys``."""
    keys = key_service.get_user_keys(user_id)
    return [key_service.serialize_key(k) for k in keys]


# ═══════════════════════════════════════════════════════════════════════════
#  /admin/* — порт services/messenger/app/api/v1/admin.py (3 эндпойнта)
# ═══════════════════════════════════════════════════════════════════════════
#
# Авторизация: ``require_admin`` исходника -> ``api_view(auth="jwt",
# admin=True)`` (единый платформенный admin-гейт, см. htqweb/http.py). Ни
# один из трёх не участвует в participant-scoping — это модерация/аудит,
# admin видит ВСЁ.
#
# Ни один из трёх эндпойнтов исходника не объявляет ``response_model`` —
# FastAPI-сторона сериализует «сырые» ORM-объекты как есть, без
# зафиксированной формы ответа. Порт ниже отдаёт явный dict со всеми
# реальными колонками моделей (см. ``_serialize_room_admin``/
# ``_serialize_message_admin``) — тот же наблюдаемый набор полей, без
# гадания по незафиксированной форме источника.

def _serialize_room_admin(room: Room) -> dict:
    return {
        "id": room.id,
        "name": room.name,
        "storage_key": str(room.storage_key),
        "room_type": room.room_type,
        "department_path": room.department_path,
        "is_e2ee": room.is_e2ee,
        "avatar_url": room.avatar_url,
        "created_at": room.created_at.isoformat(),
        "updated_at": room.updated_at.isoformat() if room.updated_at else None,
    }


def _serialize_message_admin(message: Message) -> dict:
    return {
        "id": str(message.id),
        "room_id": message.room_id,
        "sender_id": message.sender_id,
        "content": message.content,
        "is_encrypted": message.is_encrypted,
        "is_edited": message.is_edited,
        "metadata_json": message.metadata_json,
        "created_at": message.created_at.isoformat(),
        "updated_at": message.updated_at.isoformat() if message.updated_at else None,
        "attachments": [attachment_service.serialize_attachment(a) for a in message.attachments.all()],
    }


@api_view(methods=("GET",), auth="jwt", admin=True)
def admin_list_rooms(request):
    """Порт ``admin.py::list_all_rooms`` — GET /admin/rooms (``limit``/
    ``offset`` query, буквальные границы источника: ``limit`` 1..500
    (по умолчанию 50), ``offset`` >= 0 (по умолчанию 0))."""
    try:
        limit = _int_query(request, "limit", default=50, ge=1, le=500)
        offset = _int_query(request, "offset", default=0, ge=0)
    except _QueryValidationError as exc:
        return json_error(f"Invalid query parameter: {exc}", 422)

    rooms = Room.objects.order_by("id")[offset:offset + limit]
    return [_serialize_room_admin(r) for r in rooms]


@api_view(methods=("GET",), auth="jwt", admin=True)
def admin_list_room_messages(request, room_id: int):
    """Порт ``admin.py::list_messages_in_room`` — GET /admin/rooms/{id}/messages.

    Источник не пагинирует и не задаёт явный ``order_by`` (полагается на
    случайный порядок вставки БД) — порт добавляет детерминированную
    сортировку по ``created_at`` (хронологический порядок чтения для
    модерации), без изменения набора возвращаемых строк."""
    messages = (
        Message.objects.filter(room_id=room_id)
        .prefetch_related("attachments")
        .order_by("created_at")
    )
    return [_serialize_message_admin(m) for m in messages]


@api_view(methods=("POST",), auth="jwt", admin=True)
def admin_trigger_history_archive(request):
    """Порт ``admin.py::trigger_history_archive`` — POST /admin/history/archive
    (``days`` query, 1..90, по умолчанию 7). Ручной backfill/re-run —
    вызывает ТУ ЖЕ ``history_archive_service.archive_recent_history``, что и
    еженедельный beat-крон (``apps/messenger/tasks.py::archive_room_history``),
    без дублирования логики."""
    try:
        days = _int_query(request, "days", default=7, ge=1, le=90)
    except _QueryValidationError as exc:
        return json_error(f"Invalid query parameter: {exc}", 422)

    from .services import history_archive_service

    return history_archive_service.archive_recent_history(days=days)


# ═══════════════════════════════════════════════════════════════════════════
#  /users/* — порт services/messenger/app/api/v1/users.py (4 регистрации:
#  me×2 + search×2)
# ═══════════════════════════════════════════════════════════════════════════
#
# Р2 (оба — см. apps/messenger/models.py докстринг файла): исходник читал/
# писал ``chat_user_replicas``, которая здесь не портируется.
#
# ``internal/bot-message`` (S2S, ``X-Internal-Token``) и ``users/ingest``
# (``ChatUserReplica``-приёмник) удалены — P1.2/P1.3 audit-спеки
# (2026-07-22): целевых таблиц/потребителей в Django не существует, grep по
# backend/frontend/sfu на in-process вызовы не нашёл ничего живого.
# ``system_bots_service.post_bot_message`` остаётся достижим напрямую из
# ``apps.messenger.tasks.dispatch_bot_message`` (Celery), без HTTP-обвязки.

@api_view(methods=("GET",), auth="jwt")
def me(request):
    """Порт ``users.py::me`` — GET /users/me (оба написания).

    Р2: отдаёт ``apps.users.interface.get_user_brief`` — ``{id, username,
    email, full_name, is_active}`` (НЕ форма исходной ``UserReplicaRead``:
    ``first_name``/``last_name``/``avatar_url`` не выставлены users.interface,
    а прямой импорт ``apps.users.models`` отсюда запрещён, apps/core/tests/
    test_app_isolation.py). Фолбэк на минимальный профиль из JWT-claims
    сохранён (тот же случай источника — «реплика ещё не подтянута»), хотя в
    этом монолите ``apps.users.User`` практически ВСЕГДА резолвится по
    ``user_id`` живого JWT (единственная гипотетическая брешь — запись,
    удалённая из-под живого токена; ``apps.users`` физически не удаляет
    пользователей, только меняет ``UserStatus``, см. apps/users/models.py, так
    что и эта брешь на практике недостижима)."""
    brief = users_interface.get_user_brief(request.token.user_id)
    if brief is not None:
        return brief
    return {
        "id": request.token.user_id,
        "username": request.token.username or "",
        "email": None,
        "full_name": request.token.username or f"user-{request.token.user_id}",
        "is_active": True,
    }


@api_view(methods=("GET",), auth="jwt")
def search_users(request):
    """Порт ``users.py::search_users`` — GET /users/search (оба написания).

    Больше не деградирует к ``[]`` — ``apps.users.interface`` теперь несёт
    ``list_users_brief`` (задача Р3 без S2S, см. её докстринг), так что
    поиск по реальным ``apps.users.User`` (``username``/``first_name``/
    ``last_name``/``email``) больше не требует ни расширения closed-домена,
    ни воскрешения ``ChatUserReplica``. Форма ответа — ``list_users_brief``'s
    ``{id, username, email, first_name, last_name, full_name, is_active}``,
    НЕ исходная ``UserReplicaRead`` (та же деградация формы, что ``/users/
    me`` уже принял выше — first_name/last_name ЕСТЬ здесь, но нет
    ``avatar_url``).

    Сохранено из исходника: текущий пользователь исключается из результатов
    (нельзя начать чат с самим собой) и активность фильтруется — исходник
    исключал ботов через ``ChatUserReplica.is_bot``, но у ``apps.users.User``
    такого флага нет и не будет (Р2, см. ``system_bots_service.py``
    докстринг) — эта часть исходного фильтра просто неприменима здесь, не
    забыта."""
    try:
        limit = _int_query(request, "limit", default=20, ge=1, le=100)
    except _QueryValidationError as exc:
        return json_error(f"Invalid query parameter: {exc}", 422)

    q = (request.GET.get("q") or "").strip()
    # Filtering (is_active, self-exclusion) happens here, not inside
    # list_users_brief (see that function's docstring — the interface
    # doesn't filter by status, callers do). Fetched batch is generously
    # larger than ``limit`` so those two filters — which can only ever
    # SHRINK the result — don't leave us short after truncating to
    # ``limit``; 500 mirrors options_service's own picker ceiling.
    candidates = users_interface.list_users_brief(search=q or None, limit=500)
    matches = [
        u for u in candidates
        if u["is_active"] and u["id"] != request.token.user_id
    ]
    return matches[:limit]
