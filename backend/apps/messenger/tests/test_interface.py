"""Tests for ``apps/messenger/interface.py`` — workers/admin sub-task
(PLAN.md §6.5, the last messenger sub-task). Contract producer: Поток A;
consumer: ``apps.approvals`` (Поток B), see PLAN.md §7.

The generic guard test (``require_service("messenger")`` first) for
``dispatch_notification`` already lives in ``apps/core/tests/
test_parallel_scaffold.py::test_interface_stub_guards_service_first`` — this
file covers the ACTUAL behaviour (socket fan-out / system-message creation)
plus ``send_system_message``'s own guard (not covered by that generic sweep,
which only parametrizes ``dispatch_notification``).
"""
from __future__ import annotations

import json

import pytest
from unittest.mock import AsyncMock

from apps.core.models import ServiceStatus
from apps.core.services import ServiceDisabled
from apps.messenger import interface
from apps.messenger.models import Message, Room, RoomParticipant


def _disable_messenger():
    ServiceStatus.objects.update_or_create(app_label="messenger", defaults={"enabled": False})


@pytest.fixture(autouse=True)
def _mock_sio(monkeypatch):
    from apps.messenger import socket as messenger_socket

    mock_emit = AsyncMock()
    monkeypatch.setattr(messenger_socket.sio, "emit", mock_emit)
    return mock_emit


def _room(**kw):
    defaults = dict(room_type="group", name="Room")
    defaults.update(kw)
    return Room.objects.create(**defaults)


# ── require_service guards ───────────────────────────────────────────────


@pytest.mark.django_db
def test_dispatch_notification_refuses_when_messenger_disabled():
    _disable_messenger()
    with pytest.raises(ServiceDisabled):
        interface.dispatch_notification([1], {"x": 1})


@pytest.mark.django_db
def test_send_system_message_refuses_when_messenger_disabled():
    _disable_messenger()
    with pytest.raises(ServiceDisabled):
        interface.send_system_message(1, "hi")


# ── dispatch_notification ─────────────────────────────────────────────────


@pytest.mark.django_db
def test_dispatch_notification_emits_to_each_users_personal_channel(_mock_sio):
    interface.dispatch_notification([1, 2, 3], {"kind": "approval_pending", "id": 42})

    _mock_sio.assert_awaited_once_with(
        "notification", {"kind": "approval_pending", "id": 42},
        room=["user:1", "user:2", "user:3"],
    )


@pytest.mark.django_db
def test_dispatch_notification_empty_user_ids_is_a_noop(_mock_sio):
    assert interface.dispatch_notification([], {"x": 1}) is None
    _mock_sio.assert_not_awaited()


@pytest.mark.django_db
def test_dispatch_notification_returns_none():
    assert interface.dispatch_notification([1], {"x": 1}) is None


# ── send_system_message ───────────────────────────────────────────────────


@pytest.mark.django_db
def test_send_system_message_creates_message_with_no_sender(_mock_sio):
    room = _room()

    interface.send_system_message(room.id, "Заявка одобрена")

    msg = Message.objects.get(room=room)
    assert msg.sender_id is None
    assert msg.metadata_json == {"system": True}
    assert json.loads(msg.content) == {"text": "Заявка одобрена"}


@pytest.mark.django_db
def test_send_system_message_broadcasts_to_room_and_participants(_mock_sio):
    room = _room()
    RoomParticipant.objects.create(room=room, user_id=1, role="admin")
    RoomParticipant.objects.create(room=room, user_id=2, role="member")

    interface.send_system_message(room.id, "hi")

    rooms_notified = {call.kwargs["room"] for call in _mock_sio.await_args_list}
    assert rooms_notified == {f"room:{room.id}", "user:1", "user:2"}


@pytest.mark.django_db
def test_send_system_message_unknown_room_is_best_effort_noop(_mock_sio, caplog):
    with caplog.at_level("WARNING", logger="apps.messenger.interface"):
        assert interface.send_system_message(999999, "hi") is None
    assert not Message.objects.exists()
    _mock_sio.assert_not_awaited()
    assert any("send_system_message_room_not_found" in r.getMessage() for r in caplog.records)
