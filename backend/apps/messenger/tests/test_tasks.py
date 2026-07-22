"""Tests for the messenger Celery tasks (``apps/messenger/tasks.py``) —
workers/admin sub-task (PLAN.md §6.5, the last messenger sub-task).

Ported from ``services/messenger/app/workers/*.py``/``app/services/
{history_archive,system_bots}.py``. Guard tests call tasks DIRECTLY (not
through ``.delay(...)``), same style as ``apps/mail/tests/test_tasks.py``/
``apps/media_files/tests/test_media_tasks.py``.
"""
from __future__ import annotations

import datetime
import json

import pytest
from django.test import override_settings
from django.utils import timezone

from apps.core.models import ServiceStatus
from apps.core.services import ServiceDisabled
from apps.messenger import tasks
from apps.messenger.models import AuditLog, Message, Room, RoomParticipant
from apps.messenger.services import system_bots_service
from apps.users.models import User, UserStatus


def _disable_messenger():
    ServiceStatus.objects.update_or_create(app_label="messenger", defaults={"enabled": False})


def _room(**kw):
    defaults = dict(room_type="group", name="Room")
    defaults.update(kw)
    return Room.objects.create(**defaults)


# ── require_service guards ───────────────────────────────────────────────


@pytest.mark.django_db
def test_archive_room_history_refuses_when_messenger_disabled():
    _disable_messenger()
    with pytest.raises(ServiceDisabled):
        tasks.archive_room_history()


@pytest.mark.django_db
def test_audit_log_compaction_refuses_when_messenger_disabled():
    _disable_messenger()
    with pytest.raises(ServiceDisabled):
        tasks.audit_log_compaction()


@pytest.mark.django_db
def test_archive_old_messages_refuses_when_messenger_disabled():
    _disable_messenger()
    with pytest.raises(ServiceDisabled):
        tasks.archive_old_messages()


@pytest.mark.django_db
def test_dispatch_bot_message_refuses_when_messenger_disabled():
    _disable_messenger()
    with pytest.raises(ServiceDisabled):
        tasks.dispatch_bot_message(1, "bot-requests", "hi")


@pytest.mark.django_db
def test_dispatch_push_notification_refuses_when_messenger_disabled():
    _disable_messenger()
    with pytest.raises(ServiceDisabled):
        tasks.dispatch_push_notification(1, {"x": 1})


# ── archive_room_history ──────────────────────────────────────────────────


@pytest.mark.django_db
def test_archive_room_history_delegates_to_service(monkeypatch):
    called = {}

    def _fake(days):
        called["days"] = days
        return {"rooms": 1, "files_written": 0, "messages": 0, "window_start": "x"}

    import apps.messenger.services.history_archive_service as svc
    monkeypatch.setattr(svc, "archive_recent_history", _fake)

    result = tasks.archive_room_history()

    assert called["days"] == 7
    assert result["rooms"] == 1


@pytest.mark.django_db
def test_archive_room_history_writes_jsonl_via_storage(monkeypatch):
    """End-to-end (no live network): fake in-memory Storage double captures
    the JSONL bytes written by history_archive_service."""

    class _FakeStorage:
        def __init__(self):
            self.objects: dict[str, bytes] = {}

        def save(self, path, data, content_type=None):
            self.objects[path] = data

    fake = _FakeStorage()
    import apps.messenger.services.history_archive_service as svc
    monkeypatch.setattr(svc, "get_storage", lambda: fake)

    # archive_recent_history's window is [today - days, today) — i.e. it
    # deliberately EXCLUDES today's still-accumulating messages (verbatim
    # port of the source's own windowing, see history_archive_service.py) —
    # backdate the message into yesterday so a 1-day window covers it.
    room = _room()
    msg = Message.objects.create(room=room, sender_id=1, content='{"text": "hi"}')
    yesterday_noon = timezone.now().replace(hour=12, minute=0, second=0, microsecond=0) - datetime.timedelta(days=1)
    Message.objects.filter(id=msg.id).update(created_at=yesterday_noon)

    result = tasks.archive_room_history(days=1)

    assert result["messages"] == 1
    assert len(fake.objects) == 1
    key, blob = next(iter(fake.objects.items()))
    assert str(room.storage_key) in key
    line = json.loads(blob.decode("utf-8").strip())
    assert line["id"] == str(msg.id)
    assert line["content"] == '{"text": "hi"}'


# ── audit_log_compaction ──────────────────────────────────────────────────


@pytest.mark.django_db
@override_settings(AUDIT_LOG_RETENTION_DAYS=90)
def test_audit_log_compaction_deletes_only_stale_rows():
    stale = AuditLog.objects.create(action="mark_read", resource_type="RoomParticipant")
    AuditLog.objects.filter(id=stale.id).update(created_at=timezone.now() - datetime.timedelta(days=91))
    fresh = AuditLog.objects.create(action="mark_read", resource_type="RoomParticipant")

    deleted = tasks.audit_log_compaction()

    assert deleted == 1
    assert not AuditLog.objects.filter(id=stale.id).exists()
    assert AuditLog.objects.filter(id=fresh.id).exists()


# ── archive_old_messages ──────────────────────────────────────────────────


@pytest.mark.django_db
def test_archive_old_messages_is_a_logging_stub(caplog):
    with caplog.at_level("INFO", logger="apps.messenger.tasks"):
        assert tasks.archive_old_messages() is None
    assert any("archive_old_messages_run" in r.getMessage() for r in caplog.records)


# ── dispatch_bot_message ──────────────────────────────────────────────────


@pytest.mark.django_db
def test_dispatch_bot_message_unknown_bot_logs_and_returns_none(caplog):
    with caplog.at_level("WARNING", logger="apps.messenger.tasks"):
        assert tasks.dispatch_bot_message(1, "bot-nonexistent", "hi") is None
    assert any("dispatch_bot_message_unknown_bot" in r.getMessage() for r in caplog.records)


@pytest.mark.django_db
def test_dispatch_bot_message_delivers_to_known_recipient(monkeypatch):
    monkeypatch.setattr(system_bots_service, "_emit_bot_message_socket", lambda *a, **kw: None)
    u = User.objects.create(username="task-recip", email="task-recip@htq.test", password="x", status=UserStatus.ACTIVE)

    message_id = tasks.dispatch_bot_message(u.id, "bot-tasks", "Задача обновлена")

    assert message_id is not None
    msg = Message.objects.get(id=message_id)
    assert msg.sender_id == system_bots_service.BOT_TASKS.id


@pytest.mark.django_db
def test_dispatch_bot_message_unknown_recipient_returns_none():
    assert tasks.dispatch_bot_message(999999, "bot-tasks", "hi") is None


# ── dispatch_push_notification ────────────────────────────────────────────


@pytest.mark.django_db
def test_dispatch_push_notification_noop_without_keys(caplog, settings):
    assert not getattr(settings, "FCM_API_KEY", "")
    assert not getattr(settings, "APNS_CERT_PATH", "")
    with caplog.at_level("INFO", logger="apps.messenger.tasks"):
        assert tasks.dispatch_push_notification(1, {"x": 1}) is None
    assert any("push_skipped_no_keys" in r.getMessage() for r in caplog.records)


@pytest.mark.django_db
@override_settings(FCM_API_KEY="fake-key")
def test_dispatch_push_notification_logs_dispatch_when_key_configured(caplog):
    with caplog.at_level("INFO", logger="apps.messenger.tasks"):
        assert tasks.dispatch_push_notification(1, {"x": 1}) is None
    assert any("push_dispatched" in r.getMessage() for r in caplog.records)
