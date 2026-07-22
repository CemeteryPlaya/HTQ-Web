"""Контракт ``apps/messenger/socket.py`` — порт ``services/messenger/app/
api/socket.py`` (Socket.IO, Поток A фаза 8, PLAN.md §6.5).

Socket.IO трудно тестировать end-to-end (нужен реальный ASGI-транспорт) —
поэтому здесь вызываются ХЕНДЛЕРЫ НАПРЯМУЮ (``@sio.event`` не подменяет
функцию, только регистрирует её — исходная корутина вызываема как есть),
с замоканными ``sio.save_session``/``get_session``/``emit``/``enter_room``/
``leave_room`` (``AsyncMock``) и фейковыми ``environ``/``auth``. Никакой
реальный сервер/Redis не поднимается (``client_manager=None`` в тестовом
окружении, см. ``apps/messenger/socket.py::_redis_url_for_socketio``
докстринг — ``CELERY_BROKER_URL="memory://"`` в ``htqweb/settings/test.py``).

Корутины запускаются через ``asgiref.sync.async_to_sync`` (не
``@pytest.mark.anyio``/``pytest-asyncio`` — ни один из двух пакетов не
установлен как pytest-плагин в этом окружении; ``async_to_sync`` даёт тот же
результат без зависимости от anyio backend selection)."""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from asgiref.sync import async_to_sync

from apps.core.models import ServiceStatus
from apps.messenger import socket as messenger_socket
from apps.messenger.models import Room, RoomParticipant
from apps.users.models import User, UserStatus
from htqweb.authn.jwt import issue_token_pair


async def _await(coro):
    return await coro


def run(coro):
    """Runs a handler coroutine synchronously, on the SAME thread pytest-
    django's transactional fixtures use — plain ``asyncio.run()`` schedules
    ``sync_to_async`` calls onto a separate worker thread with its own DB
    connection, invisible to the test's open transaction (verified: it makes
    fixture rows/ServiceStatus flips disappear). ``async_to_sync`` sets up
    the ``CurrentThreadExecutor`` context that routes thread-sensitive
    ``sync_to_async`` calls back onto THIS thread instead."""
    return async_to_sync(_await)(coro)


@pytest.fixture(autouse=True)
def _mock_sio(monkeypatch):
    """Заменяет async-методы модульного ``sio`` на ``AsyncMock`` — тесты не
    трогают реальный Engine.IO/Redis транспорт."""
    mocks = {
        "save_session": AsyncMock(),
        "get_session": AsyncMock(),
        "enter_room": AsyncMock(),
        "leave_room": AsyncMock(),
        "emit": AsyncMock(),
    }
    for name, mock in mocks.items():
        monkeypatch.setattr(messenger_socket.sio, name, mock)
    return mocks


@pytest.fixture
def user(db):
    u = User.objects.create(username="ws-user", email="ws-user@htq.test", password="x", status=UserStatus.ACTIVE)
    u.set_password("S3cret!Pass1")
    u.save()
    return u


@pytest.fixture
def other_user(db):
    u = User.objects.create(username="ws-other", email="ws-other@htq.test", password="x", status=UserStatus.ACTIVE)
    u.set_password("S3cret!Pass1")
    u.save()
    return u


def _token_for(u) -> str:
    return issue_token_pair(u)["access"]


def _environ(query_string: str = "") -> dict:
    return {"QUERY_STRING": query_string}


def _direct_room(a_id: int, b_id: int) -> Room:
    room = Room.objects.create(room_type="direct")
    RoomParticipant.objects.create(room=room, user_id=a_id, role="admin")
    RoomParticipant.objects.create(room=room, user_id=b_id, role="member")
    return room


# ── connect: require_service("messenger") гейт (Р10) ────────────────────────

@pytest.mark.django_db
def test_connect_rejected_when_messenger_disabled(user, _mock_sio):
    ServiceStatus.objects.update_or_create(app_label="messenger", defaults={"enabled": False})

    with pytest.raises(messenger_socket.socketio.exceptions.ConnectionRefusedError):
        run(messenger_socket.connect("sid-1", _environ(), {"token": _token_for(user)}))

    _mock_sio["save_session"].assert_not_called()


# ── connect: JWT-валидация ───────────────────────────────────────────────────

@pytest.mark.django_db
def test_connect_rejected_when_token_missing(_mock_sio):
    with pytest.raises(messenger_socket.socketio.exceptions.ConnectionRefusedError):
        run(messenger_socket.connect("sid-1", _environ(), None))
    _mock_sio["save_session"].assert_not_called()


@pytest.mark.django_db
def test_connect_rejected_when_token_invalid(_mock_sio):
    with pytest.raises(messenger_socket.socketio.exceptions.ConnectionRefusedError):
        run(messenger_socket.connect("sid-1", _environ(), {"token": "not-a-real-jwt"}))
    _mock_sio["save_session"].assert_not_called()


@pytest.mark.django_db
def test_connect_falls_back_to_query_string_token(user, _mock_sio):
    token = _token_for(user)
    run(messenger_socket.connect("sid-1", _environ(f"token={token}"), None))
    _mock_sio["save_session"].assert_awaited_once()


# ── connect: успех — session + presence (auto-join) ─────────────────────────

@pytest.mark.django_db
def test_connect_valid_token_saves_session_and_autojoins_rooms(user, other_user, _mock_sio):
    room = _direct_room(user.id, other_user.id)

    run(messenger_socket.connect("sid-1", _environ(), {"token": _token_for(user)}))

    _mock_sio["save_session"].assert_awaited_once_with(
        "sid-1", {"user_id": user.id, "username": user.username, "is_admin": False},
    )
    entered = {call.args[1] for call in _mock_sio["enter_room"].await_args_list}
    assert entered == {f"room:{room.id}", f"user:{user.id}"}


@pytest.mark.django_db
def test_connect_admin_flag_reflects_token_claim(_mock_sio):
    """is_staff -> is_admin=True в JWT (htqweb.authn.jwt._base_claims) должно
    попасть в session как есть."""
    admin = User.objects.create(
        username="ws-admin", email="ws-admin@htq.test", password="x",
        status=UserStatus.ACTIVE, is_staff=True,
    )
    admin.set_password("S3cret!Pass1")
    admin.save()

    run(messenger_socket.connect("sid-2", _environ(), {"token": _token_for(admin)}))
    saved = _mock_sio["save_session"].await_args.args[1]
    assert saved["is_admin"] is True


@pytest.mark.django_db
def test_connect_does_not_raise_when_autojoin_query_fails(user, monkeypatch, _mock_sio):
    """Порт try/except исходника: сбой авто-join НЕ должен блокировать
    connect (session уже сохранена)."""
    def _boom(_user_id):
        raise RuntimeError("db hiccup")

    monkeypatch.setattr(messenger_socket, "_user_room_ids_sync", _boom)

    run(messenger_socket.connect("sid-1", _environ(), {"token": _token_for(user)}))

    _mock_sio["save_session"].assert_awaited_once()


# ── disconnect ────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_disconnect_handles_missing_session(_mock_sio):
    _mock_sio["get_session"].side_effect = KeyError("sid-1")
    run(messenger_socket.disconnect("sid-1"))  # no raise


@pytest.mark.django_db
def test_disconnect_logs_known_session(_mock_sio):
    _mock_sio["get_session"].return_value = {"user_id": 42}
    run(messenger_socket.disconnect("sid-1"))  # no raise


# ── join_room: participant-scoping ───────────────────────────────────────────

@pytest.mark.django_db
def test_join_room_denied_when_not_a_participant(user, other_user, _mock_sio):
    room = _direct_room(other_user.id, user.id + 999)  # user is NOT a participant
    _mock_sio["get_session"].return_value = {"user_id": user.id}

    result = run(messenger_socket.join_room("sid-1", {"room_id": room.id}))

    assert result == {"ok": False, "error": "not_a_member"}
    _mock_sio["enter_room"].assert_not_awaited()


@pytest.mark.django_db
def test_join_room_allowed_when_participant(user, other_user, _mock_sio):
    room = _direct_room(user.id, other_user.id)
    _mock_sio["get_session"].return_value = {"user_id": user.id}

    result = run(messenger_socket.join_room("sid-1", {"room_id": room.id}))

    assert result == {"ok": True}
    _mock_sio["enter_room"].assert_awaited_once_with("sid-1", f"room:{room.id}")


@pytest.mark.django_db
def test_join_room_missing_room_id(user, _mock_sio):
    _mock_sio["get_session"].return_value = {"user_id": user.id}
    result = run(messenger_socket.join_room("sid-1", {}))
    assert result == {"ok": False, "error": "missing_room_id"}


@pytest.mark.django_db
def test_join_room_invalid_room_id(user, _mock_sio):
    _mock_sio["get_session"].return_value = {"user_id": user.id}
    result = run(messenger_socket.join_room("sid-1", {"room_id": "not-an-int"}))
    assert result == {"ok": False, "error": "invalid_room_id"}


# ── leave_room ────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_leave_room_success(_mock_sio):
    result = run(messenger_socket.leave_room("sid-1", {"room_id": 7}))
    assert result == {"ok": True}
    _mock_sio["leave_room"].assert_awaited_once_with("sid-1", "room:7")


@pytest.mark.django_db
def test_leave_room_missing_room_id(_mock_sio):
    result = run(messenger_socket.leave_room("sid-1", {}))
    assert result == {"ok": False, "error": "missing_room_id"}


# ── typing ────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_typing_emits_to_room_skipping_sender(user, _mock_sio):
    _mock_sio["get_session"].return_value = {"user_id": user.id}

    run(messenger_socket.typing("sid-1", {"room_id": 7, "is_typing": True}))

    _mock_sio["emit"].assert_awaited_once_with(
        "user_typing", {"room_id": 7, "user_id": user.id, "is_typing": True},
        room="room:7", skip_sid="sid-1",
    )


@pytest.mark.django_db
def test_typing_noop_without_room_id(user, _mock_sio):
    _mock_sio["get_session"].return_value = {"user_id": user.id}
    run(messenger_socket.typing("sid-1", {}))
    _mock_sio["emit"].assert_not_awaited()


# ── mark_read: WS-side read-receipt ──────────────────────────────────────────

@pytest.mark.django_db
def test_mark_read_persists_and_broadcasts(user, other_user, _mock_sio):
    room = _direct_room(user.id, other_user.id)
    message_id = "11111111-1111-1111-1111-111111111111"
    _mock_sio["get_session"].return_value = {"user_id": user.id}

    run(messenger_socket.mark_read("sid-1", {"room_id": room.id, "message_id": message_id}))

    rp = RoomParticipant.objects.get(room_id=room.id, user_id=user.id)
    assert str(rp.last_read_message_id) == message_id
    _mock_sio["emit"].assert_awaited_once_with(
        "message_read",
        {"room_id": room.id, "message_id": message_id, "reader_user_id": user.id},
        room=f"room:{room.id}", skip_sid="sid-1",
    )


@pytest.mark.django_db
def test_mark_read_noop_when_not_a_participant(user, other_user, _mock_sio):
    room = Room.objects.create(room_type="direct")
    RoomParticipant.objects.create(room=room, user_id=other_user.id, role="admin")
    _mock_sio["get_session"].return_value = {"user_id": user.id}

    run(messenger_socket.mark_read(
        "sid-1", {"room_id": room.id, "message_id": "11111111-1111-1111-1111-111111111111"},
    ))

    _mock_sio["emit"].assert_not_awaited()


@pytest.mark.django_db
def test_mark_read_noop_without_message_id(user, _mock_sio):
    _mock_sio["get_session"].return_value = {"user_id": user.id}
    run(messenger_socket.mark_read("sid-1", {"room_id": 1}))
    _mock_sio["emit"].assert_not_awaited()


# ── manager selection (декларативный, из брифа п.1) ─────────────────────────

def test_client_manager_is_none_in_test_settings():
    """settings.test:CELERY_BROKER_URL="memory://" -> НЕ redis:// -> дефолтный
    in-memory manager (client_manager=None), не AsyncRedisManager."""
    assert messenger_socket._redis_url_for_socketio() is None


def test_redis_url_detection_accepts_redis_scheme(settings):
    settings.CELERY_BROKER_URL = "redis://localhost:6379/9"
    assert messenger_socket._redis_url_for_socketio() == "redis://localhost:6379/9"
