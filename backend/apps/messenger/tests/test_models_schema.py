"""Паритет схемы messenger-core с FastAPI-исходником
(``services/messenger/app/models/{domain,audit_log}.py``).

Порт-источники:
  * services/messenger/app/models/domain.py::Room
  * services/messenger/app/models/domain.py::RoomParticipant
  * services/messenger/app/models/domain.py::Message
  * services/messenger/app/models/audit_log.py::AuditLog
  * services/messenger/app/models/base.py::TimestampMixin (created_at
    индексирован, updated_at — нет; оба server_default=now())

Решение D2: дефолтные Django-имена таблиц — messenger_room,
messenger_roomparticipant, messenger_message, messenger_auditlog. Р2:
``chat_user_replicas`` НЕ портируется — см. apps/messenger/models.py
докстринг файла.
"""
import uuid

import pytest
from django.db import connection
from django.db.utils import IntegrityError

from apps.messenger.models import ChatAttachment, Message, Room, RoomParticipant, UserKey


def _cols(table: str) -> dict:
    with connection.cursor() as cur:
        cur.execute(
            "SELECT column_name, is_nullable, column_default "
            "FROM information_schema.columns WHERE table_name = %s",
            [table],
        )
        return {r[0]: {"nullable": r[1] == "YES", "default": r[2]} for r in cur.fetchall()}


def _indexed_columns(table: str) -> set[str]:
    with connection.cursor() as cur:
        cur.execute("SELECT indexdef FROM pg_indexes WHERE tablename = %s", [table])
        defs = [r[0] for r in cur.fetchall()]
    cols: set[str] = set()
    for d in defs:
        inner = d[d.rfind("(") + 1 : d.rfind(")")]
        for part in inner.split(","):
            token = part.strip().strip('"').split()[0]
            cols.add(token.strip('"'))
    return cols


# ── таблицы — дефолтные Django-имена (решение D2) ───────────────────────────

@pytest.mark.django_db
def test_default_table_names():
    with connection.cursor() as cur:
        cur.execute("SELECT tablename FROM pg_tables WHERE tablename LIKE 'messenger_%'")
        tables = {r[0] for r in cur.fetchall()}
    assert {
        "messenger_room", "messenger_roomparticipant", "messenger_message", "messenger_auditlog",
    } <= tables


# ── Room ─────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_room_columns_and_defaults():
    cols = _cols("messenger_room")
    assert cols["name"]["nullable"]
    assert not cols["storage_key"]["nullable"]
    assert cols["storage_key"]["default"] is None  # клиентский default, не server_default
    assert not cols["room_type"]["nullable"]
    assert cols["department_path"]["nullable"]
    assert cols["is_e2ee"]["default"] is None  # клиентский default (Python-side), см. D-mail-1
    assert cols["avatar_url"]["nullable"]
    assert cols["created_at"]["default"] is not None
    assert cols["updated_at"]["default"] is not None
    assert {"created_at", "storage_key"} <= _indexed_columns("messenger_room")


@pytest.mark.django_db
def test_room_field_defaults_on_create():
    room = Room.objects.create()
    assert room.room_type == "direct"
    assert room.is_e2ee is False
    assert room.storage_key is not None
    assert room.created_at is not None
    assert room.updated_at is not None


@pytest.mark.django_db
def test_room_storage_key_unique():
    key = uuid.uuid4()
    Room.objects.create(storage_key=key)
    with pytest.raises(IntegrityError):
        Room.objects.create(storage_key=key)


# ── RoomParticipant ──────────────────────────────────────────────────────

@pytest.mark.django_db
def test_room_participant_composite_pk_columns():
    cols = _cols("messenger_roomparticipant")
    assert not cols["room_id"]["nullable"]
    assert not cols["user_id"]["nullable"]
    assert not cols["role"]["nullable"]
    assert cols["last_read_message_id"]["nullable"]
    # user_id — без ОТДЕЛЬНОГО FK/индекса (Р2: chat_user_replicas не
    # портируется): единственный индекс, где встречается user_id — составной
    # PK-индекс (room_id, user_id) сам по себе; отдельного btree только по
    # user_id нет (в отличие от, скажем, PMODepartment.department в hr,
    # который НЕ левый префикс и потому несёт собственный авто-индекс FK).
    with connection.cursor() as cur:
        cur.execute("SELECT indexdef FROM pg_indexes WHERE tablename = %s", ["messenger_roomparticipant"])
        defs = [r[0] for r in cur.fetchall()]
    solo_user_id_indexes = [d for d in defs if "(user_id)" in d]
    assert solo_user_id_indexes == [], solo_user_id_indexes


@pytest.mark.django_db
def test_room_participant_field_defaults_on_create():
    room = Room.objects.create()
    rp = RoomParticipant.objects.create(room=room, user_id=1)
    assert rp.role == "member"
    assert rp.last_read_message_id is None
    assert rp.created_at is not None


@pytest.mark.django_db
def test_room_participant_composite_pk_uniqueness():
    room = Room.objects.create()
    RoomParticipant.objects.create(room=room, user_id=1)
    with pytest.raises(IntegrityError):
        RoomParticipant.objects.create(room=room, user_id=1)


@pytest.mark.django_db
def test_room_participant_cascade_delete_on_room():
    room = Room.objects.create()
    RoomParticipant.objects.create(room=room, user_id=1)
    room.delete()
    assert not RoomParticipant.objects.filter(user_id=1).exists()


# ── Message ──────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_message_columns_and_defaults():
    cols = _cols("messenger_message")
    assert not cols["room_id"]["nullable"]
    assert cols["sender_id"]["nullable"]
    assert not cols["content"]["nullable"]
    assert cols["is_encrypted"]["default"] is None
    assert cols["is_edited"]["default"] is None
    assert cols["created_at"]["default"] is not None
    assert cols["updated_at"]["default"] is not None
    assert {"room_id", "created_at"} <= _indexed_columns("messenger_message")


@pytest.mark.django_db
def test_message_field_defaults_on_create():
    room = Room.objects.create()
    msg = Message.objects.create(room=room, content="hi")
    assert msg.is_encrypted is False
    assert msg.is_edited is False
    assert msg.sender_id is None
    assert isinstance(msg.id, uuid.UUID)


@pytest.mark.django_db
def test_message_cascade_delete_on_room():
    room = Room.objects.create()
    msg = Message.objects.create(room=room, content="hi")
    room.delete()
    assert not Message.objects.filter(id=msg.id).exists()


# ── AuditLog(messenger) ─────────────────────────────────────────────────

@pytest.mark.django_db
def test_audit_log_columns():
    cols = _cols("messenger_auditlog")
    assert cols["user_id"]["nullable"]
    assert not cols["action"]["nullable"]
    assert not cols["resource_type"]["nullable"]
    assert cols["resource_id"]["nullable"]
    assert cols["changes"]["nullable"]
    assert cols["created_at"]["default"] is not None
    assert "updated_at" not in cols  # источник не несёт updated_at
    assert {"user_id", "action", "resource_id", "correlation_id", "created_at"} <= (
        _indexed_columns("messenger_auditlog")
    )


@pytest.mark.django_db(transaction=True)
def test_message_invalid_room_fk_raises_integrity_error():
    """FK DEFERRABLE INITIALLY DEFERRED (Django-дефолт на Postgres) — нужен
    transaction=True, иначе проверка не сработает внутри тестовой обёрточной
    транзакции (см. apps/hr/tests/test_documents_api.py, тот же паттерн).
    ⚠️ env-флак: transaction=True в комбинированном прогоне иногда даёт
    SystemExit при teardown — перепроверяй в изоляции, это не дефект теста."""
    with pytest.raises(IntegrityError):
        Message.objects.create(room_id=999999, content="orphan")


# ── ChatAttachment (attachments-под-задача) ─────────────────────────────

@pytest.mark.django_db
def test_chat_attachment_columns_and_defaults():
    cols = _cols("messenger_chatattachment")
    assert cols["message_id"]["nullable"]
    assert cols["room_id"]["nullable"]
    assert cols["file_metadata_id"]["nullable"]
    assert not cols["filename"]["nullable"]
    assert not cols["size"]["nullable"]
    assert not cols["content_type"]["nullable"]
    assert cols["data_type"]["default"] is not None
    assert cols["storage_path"]["nullable"]
    assert cols["public_url"]["nullable"]
    assert cols["thumbnail_path"]["nullable"]
    assert cols["width"]["nullable"]
    assert cols["height"]["nullable"]
    assert not cols["uploaded_by"]["nullable"]
    assert cols["created_at"]["default"] is not None
    assert cols["updated_at"]["default"] is not None
    # message_id/room_id — авто-индекс FK (паритет с ix_chat_attachments_*
    # исходника); uploaded_by — БЕЗ отдельного индекса (Р2: не FK, источник
    # тоже не индексировал эту колонку отдельно).
    assert {"message_id", "room_id", "created_at"} <= _indexed_columns("messenger_chatattachment")
    with connection.cursor() as cur:
        cur.execute(
            "SELECT indexdef FROM pg_indexes WHERE tablename = %s", ["messenger_chatattachment"],
        )
        defs = [r[0] for r in cur.fetchall()]
    assert [d for d in defs if "(uploaded_by)" in d] == []


@pytest.mark.django_db
def test_chat_attachment_field_defaults_on_create():
    room = Room.objects.create()
    att = ChatAttachment.objects.create(
        room=room, filename="a.png", size=10, content_type="image/png", uploaded_by=1,
    )
    assert att.data_type == "other"
    assert att.message_id is None
    assert att.storage_path is None
    assert att.thumbnail_path is None
    assert att.width is None
    assert att.height is None
    assert isinstance(att.id, uuid.UUID)


@pytest.mark.django_db
def test_chat_attachment_cascade_delete_on_room():
    room = Room.objects.create()
    att = ChatAttachment.objects.create(
        room=room, filename="a.png", size=10, content_type="image/png", uploaded_by=1,
    )
    room.delete()
    assert not ChatAttachment.objects.filter(id=att.id).exists()


@pytest.mark.django_db
def test_chat_attachment_cascade_delete_on_message():
    room = Room.objects.create()
    msg = Message.objects.create(room=room, content="hi")
    att = ChatAttachment.objects.create(
        room=room, message=msg, filename="a.png", size=10, content_type="image/png", uploaded_by=1,
    )
    msg.delete()
    assert not ChatAttachment.objects.filter(id=att.id).exists()


@pytest.mark.django_db(transaction=True)
def test_chat_attachment_invalid_room_fk_raises_integrity_error():
    """⚠️ env-флак: transaction=True в комбинированном прогоне иногда даёт
    SystemExit при teardown — перепроверяй в изоляции, это не дефект теста."""
    with pytest.raises(IntegrityError):
        ChatAttachment.objects.create(
            room_id=999999, filename="a.png", size=1, content_type="x", uploaded_by=1,
        )


# ── UserKey (attachments-под-задача) ────────────────────────────────────

@pytest.mark.django_db
def test_user_key_composite_pk_columns():
    cols = _cols("messenger_userkey")
    assert not cols["user_id"]["nullable"]
    assert not cols["device_id"]["nullable"]
    assert not cols["public_identity_key"]["nullable"]
    assert not cols["signed_pre_key"]["nullable"]
    assert not cols["signature"]["nullable"]
    assert cols["created_at"]["default"] is not None


@pytest.mark.django_db
def test_user_key_composite_pk_uniqueness():
    UserKey.objects.create(
        user_id=1, device_id="dev-1", public_identity_key="a", signed_pre_key="b", signature="c",
    )
    with pytest.raises(IntegrityError):
        UserKey.objects.create(
            user_id=1, device_id="dev-1", public_identity_key="x", signed_pre_key="y", signature="z",
        )


@pytest.mark.django_db
def test_user_key_different_devices_allowed():
    UserKey.objects.create(
        user_id=1, device_id="dev-1", public_identity_key="a", signed_pre_key="b", signature="c",
    )
    UserKey.objects.create(
        user_id=1, device_id="dev-2", public_identity_key="a2", signed_pre_key="b2", signature="c2",
    )
    assert UserKey.objects.filter(user_id=1).count() == 2
