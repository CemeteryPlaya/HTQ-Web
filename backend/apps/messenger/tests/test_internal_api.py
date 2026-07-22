"""Контракт POST /api/messenger/v1/internal/bot-message — паритет с
``services/messenger/app/api/v1/internal.py::send_bot_message_endpoint``
(workers/admin под-задача, PLAN.md §6.5, последняя под-задача messenger).

S2S-эндпойнт: общий секрет в заголовке ``X-Internal-Token``, сверяемый с
``INTERNAL_S2S_TOKEN`` (или legacy ``MESSENGER_INTERNAL_TOKEN`` — буквальное
имя переменной исходника) — тот же приём, что уже установлен
``apps/hr/views.py::_check_internal_token``/``internal_supervisor`` (см.
``apps/messenger/views.py`` докстринг секции для полного обоснования решения
переиспользовать этот механизм, а не переводить на ``admin=True``).

Также покрывает ``apps/messenger/services/system_bots_service.py::
post_bot_message`` (через этот же HTTP-путь — единственный вызывающий).
"""
from __future__ import annotations

import json

import pytest
from django.test import Client

from apps.messenger.models import Message, Room, RoomParticipant
from apps.messenger.services import system_bots_service
from apps.users.models import User, UserStatus

BASE = "/api/messenger/v1/internal/bot-message"


@pytest.fixture(autouse=True)
def internal_token(monkeypatch):
    monkeypatch.setenv("INTERNAL_S2S_TOKEN", "s2s-secret")
    monkeypatch.delenv("MESSENGER_INTERNAL_TOKEN", raising=False)
    return "s2s-secret"


@pytest.fixture
def recipient(db):
    u = User.objects.create(
        username="bot-recipient", email="bot-recipient@htq.test", password="x", status=UserStatus.ACTIVE,
    )
    u.set_password("S3cret!Pass1")
    u.save()
    return u


def _post(body, **headers):
    return Client().post(BASE, data=json.dumps(body), content_type="application/json", **headers)


# ── token gate ────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_missing_token_configured_gives_503(monkeypatch):
    monkeypatch.delenv("INTERNAL_S2S_TOKEN", raising=False)
    monkeypatch.delenv("MESSENGER_INTERNAL_TOKEN", raising=False)
    resp = _post({"bot": "bot-requests", "user_id": 1, "text": "hi"})
    assert resp.status_code == 503


@pytest.mark.django_db
def test_wrong_token_401():
    resp = _post({"bot": "bot-requests", "user_id": 1, "text": "hi"}, HTTP_X_INTERNAL_TOKEN="wrong")
    assert resp.status_code == 401


@pytest.mark.django_db
def test_missing_token_header_401():
    resp = _post({"bot": "bot-requests", "user_id": 1, "text": "hi"})
    assert resp.status_code == 401


@pytest.mark.django_db
def test_token_checked_before_body_validation(monkeypatch):
    """Невалидное тело + неверный токен -> 401 (не 422): токен проверяется
    ПЕРВЫМ, тот же порядок, что hr's internal_supervisor."""
    resp = Client().post(
        BASE, data="not json at all", content_type="application/json", HTTP_X_INTERNAL_TOKEN="wrong",
    )
    assert resp.status_code == 401


# ── body validation ───────────────────────────────────────────────────────


@pytest.mark.django_db
def test_invalid_body_422():
    resp = _post({"bot": "bot-requests"}, HTTP_X_INTERNAL_TOKEN="s2s-secret")  # missing user_id/text
    assert resp.status_code == 422


@pytest.mark.django_db
def test_unknown_bot_400(recipient):
    resp = _post(
        {"bot": "bot-nonexistent", "user_id": recipient.id, "text": "hi"},
        HTTP_X_INTERNAL_TOKEN="s2s-secret",
    )
    assert resp.status_code == 400


# ── happy path ────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_bot_message_delivered_to_known_recipient(recipient, monkeypatch):
    monkeypatch.setattr(system_bots_service, "_emit_bot_message_socket", lambda *a, **kw: None)

    resp = _post(
        {"bot": "bot-requests", "user_id": recipient.id, "text": "Заявка одобрена"},
        HTTP_X_INTERNAL_TOKEN="s2s-secret",
    )

    assert resp.status_code == 202
    body = resp.json()
    assert body["delivered"] is True
    assert body["message_id"] is not None

    msg = Message.objects.get(id=body["message_id"])
    assert msg.sender_id == system_bots_service.BOT_REQUESTS.id
    assert json.loads(msg.content) == {"text": "Заявка одобрена"}


@pytest.mark.django_db
def test_bot_message_creates_dm_room_lazily(recipient, monkeypatch):
    monkeypatch.setattr(system_bots_service, "_emit_bot_message_socket", lambda *a, **kw: None)

    _post(
        {"bot": "bot-calendar", "user_id": recipient.id, "text": "Напоминание"},
        HTTP_X_INTERNAL_TOKEN="s2s-secret",
    )

    room = Room.objects.get(room_type="direct")
    participant_ids = set(RoomParticipant.objects.filter(room=room).values_list("user_id", flat=True))
    assert participant_ids == {recipient.id, system_bots_service.BOT_CALENDAR.id}


@pytest.mark.django_db
def test_bot_message_reuses_existing_dm_room(recipient, monkeypatch):
    monkeypatch.setattr(system_bots_service, "_emit_bot_message_socket", lambda *a, **kw: None)

    _post({"bot": "bot-news", "user_id": recipient.id, "text": "Первое"}, HTTP_X_INTERNAL_TOKEN="s2s-secret")
    _post({"bot": "bot-news", "user_id": recipient.id, "text": "Второе"}, HTTP_X_INTERNAL_TOKEN="s2s-secret")

    assert Room.objects.filter(room_type="direct").count() == 1


@pytest.mark.django_db
def test_bot_message_not_delivered_for_unknown_recipient(monkeypatch):
    resp = _post(
        {"bot": "bot-requests", "user_id": 999999, "text": "hi"}, HTTP_X_INTERNAL_TOKEN="s2s-secret",
    )
    assert resp.status_code == 202
    body = resp.json()
    assert body == {"delivered": False, "message_id": None}
    assert not Message.objects.exists()


@pytest.mark.django_db
def test_bot_id_itself_is_not_a_valid_recipient(monkeypatch):
    """Р2: без is_bot-флага в apps.users, отсечение «получатель — другой
    бот» достигается тем же guard'ом «получатель неизвестен» — id бота
    заведомо никогда не существует как строка apps.users.User (см.
    system_bots_service.py докстринг)."""
    resp = _post(
        {"bot": "bot-requests", "user_id": system_bots_service.BOT_CALENDAR.id, "text": "hi"},
        HTTP_X_INTERNAL_TOKEN="s2s-secret",
    )
    assert resp.status_code == 202
    assert resp.json() == {"delivered": False, "message_id": None}
