"""Модели домена messenger — messenger-core: порт
``services/messenger/app/models/domain.py`` (Room, RoomParticipant, Message)
+ ``services/messenger/app/models/audit_log.py`` (AuditLog).

Таблицы — дефолтные Django-имена (решение D2, как apps.hr/apps.mail):
messenger_room, messenger_roomparticipant, messenger_message,
messenger_auditlog (старые имена исходника — rooms, room_participants,
messages, audit_log — только в ETL-карте будущей фазы). Схема — ТОЛЬКО
public (PgBouncer transaction-mode роняет search_path, см. CLAUDE.md); в
исходнике таблицы жили в схеме ``messenger``, здесь это не переносится.

Р2 (см. messenger-core-brief.md): ``services/messenger/app/models/
domain.py::ChatUserReplica`` НЕ портируется — денормализованная реплика
платформенных пользователей, которой не место в монолите (пользователи уже
свои же Django-строки, ``apps.users.models.User``). Поэтому
``RoomParticipant.user_id``/``Message.sender_id`` здесь — ГОЛЫЕ
``IntegerField`` БЕЗ ForeignKey: ни на ``chat_user_replicas`` (которой нет),
ни на ``apps.users.User`` (межаппных FK нет — apps/core/tests/
test_app_isolation.py). Данные пользователя (имя, признак активности) —
ТОЛЬКО через ``apps.users.interface.get_user_brief``/``get_users_brief``, см.
``apps/messenger/services/messenger_service.py``.

``ChatAttachment``/``UserKey`` (attachments/keys под-задачи, PLAN.md §6.5) —
НЕ переносятся сейчас: ``Message`` не несёт accessor к вложениям,
сериализация ``attachments`` — пустой список-заглушка до той под-задачи (см.
``messenger_service.py``). ``Room.storage_key`` (нужен только вложениям)
перенесён для паритета схемы модели ``Room``, хоть и не используется до
attachments-под-задачи.
"""
from __future__ import annotations

import uuid

from django.db import models
from django.db.models.functions import Now


class RoomType(models.TextChoices):
    """Порт комментария исходника: ``room_type: ... # direct, group,
    department``. Исходная колонка (``String(20)``) НЕ несёт CheckConstraint
    на это множество (тот же принцип, что ``apps.mail.models.Folder``/
    ``OAuthProvider``) — choices здесь чисто для админки/документации, без
    ограничения на уровне БД. ``department`` встречается только в комментарии
    исходника — ни один эндпойнт messenger-core его не устанавливает/не
    проверяет (перенесено как есть, без домысливания логики)."""

    DIRECT = "direct", "Личный чат"
    GROUP = "group", "Группа"
    DEPARTMENT = "department", "Отдел"


class RoomParticipantRole(models.TextChoices):
    """Порт комментария исходника: ``role: ... # admin, member``. Без
    CheckConstraint в исходнике — тот же принцип, что ``RoomType`` выше."""

    ADMIN = "admin", "Администратор"
    MEMBER = "member", "Участник"


class Room(models.Model):
    """Порт ``services/messenger/app/models/domain.py::Room``
    (Base, IntIdMixin, TimestampMixin)."""

    name = models.CharField(max_length=255, null=True, blank=True)
    # Уникальный ключ для S3-хранилища вложений (attachments-под-задача) —
    # клиентский Python-дефолт исходника (``default=uuid.uuid4``, БЕЗ
    # server_default) -> переносится как ``default=`` БЕЗ ``db_default``
    # (тот же принцип, что ``apps.mail.models.OAuthToken.is_active``).
    storage_key = models.UUIDField(default=uuid.uuid4, unique=True)
    room_type = models.CharField(
        max_length=20, choices=RoomType.choices, default=RoomType.DIRECT,
    )
    # D1 (см. apps/hr/models.py::Department.path докстринг): исходная
    # колонка объявлена как PG-ltree (``LtreeType``, app/models/types.py),
    # но расширение ltree нигде в порту не подключено — переносится как
    # обычная индексируемая строка-путь. Ни один эндпойнт messenger-core не
    # читает/пишет это поле (используется бы отделными/department-комнатами,
    # которых в scope этой под-задачи нет).
    department_path = models.CharField(max_length=500, null=True, blank=True)
    is_e2ee = models.BooleanField(default=False)
    # Групповой аватар (attachments-под-задача выставляет через
    # ``POST /attachments/upload/``) — сырое значение колонки, без
    # пере-подписания signed-URL (``_refresh_signed_avatar`` исходника,
    # ``schemas/messenger.py``) до той под-задачи.
    avatar_url = models.CharField(max_length=1024, null=True, blank=True)

    created_at = models.DateTimeField(db_default=Now(), db_index=True)
    updated_at = models.DateTimeField(db_default=Now(), auto_now=True)

    def __str__(self) -> str:
        return f"<Room(id={self.id}, room_type={self.room_type!r})>"


class RoomParticipant(models.Model):
    """Порт ``::RoomParticipant``. Составной PK (``room_id``, ``user_id``) —
    оба поля были ``primary_key=True`` у исходника, без суррогатного id ->
    Django 5.2 ``CompositePrimaryKey`` (см. ``apps/hr/models.py::
    PMODepartment`` докстринг для прецедента этого приёма в этом репо).

    ``room`` — ``db_index=False``: составной PK уже покрывает эту колонку
    ЛЕВЫМ префиксом (тот же приём, что ``PMODepartment.pmo``) — отдельный
    btree-индекс поверх был бы чистым дублем.

    ``user_id`` — Р2: НЕ FK (``chat_user_replicas`` не портируется, см.
    докстринг модуля выше). Не покрыт левым префиксом составного PK, но в
    исходнике тоже не было отдельного индекса на этой колонке (обычный
    ``mapped_column(ForeignKey(...), primary_key=True)`` без ``index=True``)
    — оставлено без ``db_index``, буквальное соответствие.

    ВНИМАНИЕ (админка): модели с ``CompositePrimaryKey`` Django-admin
    регистрировать нельзя — ``AdminSite.register`` безусловно поднимает
    ``ImproperlyConfigured`` для любой модели с ``_meta.is_composite_pk``,
    до какого-либо участия ``ModelAdmin``/миксинов (см. apps/hr/admin.py,
    комментарий над PMODepartment/PMOPosition). ``RoomParticipant`` поэтому
    НЕ зарегистрирована в apps/messenger/admin.py — так же, как
    PMODepartment/PMOPosition в hr.
    """

    room = models.ForeignKey(
        Room, on_delete=models.CASCADE, related_name="participants", db_index=False,
    )
    user_id = models.IntegerField()
    role = models.CharField(
        max_length=20, choices=RoomParticipantRole.choices,
        default=RoomParticipantRole.MEMBER,
    )
    last_read_message_id = models.UUIDField(null=True, blank=True)

    created_at = models.DateTimeField(db_default=Now(), db_index=True)
    updated_at = models.DateTimeField(db_default=Now(), auto_now=True)

    pk = models.CompositePrimaryKey("room", "user_id")

    def __str__(self) -> str:
        return f"<RoomParticipant(room_id={self.room_id}, user_id={self.user_id})>"


class Message(models.Model):
    """Порт ``::Message``. ``sender_id`` — Р2: НЕ FK (см. докстринг модуля
    выше); исходник — ``ForeignKey(..., ondelete="SET_NULL")``, nullable.
    Здесь просто nullable ``IntegerField`` — SET_NULL воспроизвести нечем без
    FK, но той функциональности и не было бы: ``apps.users`` не удаляет
    пользователей физически, только меняет ``UserStatus`` (см.
    apps/users/models.py), так что каскад на удаление никогда не сработал бы
    и в этом монолите."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # Исходник несёт явный ``index=True`` на этой колонке (сверх обычного
    # FK) — Django FK индексирует сам по умолчанию, отдельная пометка не
    # нужна (тот же принцип, что EmailMessage.account в apps/mail/models.py).
    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name="messages")
    sender_id = models.IntegerField(null=True, blank=True)
    content = models.TextField()
    is_encrypted = models.BooleanField(default=False)
    metadata_json = models.JSONField(null=True, blank=True)
    is_edited = models.BooleanField(default=False)

    created_at = models.DateTimeField(db_default=Now(), db_index=True)
    updated_at = models.DateTimeField(db_default=Now(), auto_now=True)

    def __str__(self) -> str:
        return f"<Message(id={self.id}, room_id={self.room_id})>"


class AuditLog(models.Model):
    """Порт ``services/messenger/app/models/audit_log.py::AuditLog`` —
    аудит-таблица ДОМЕНА messenger (своя, отдельная от hr_auditlog/
    mail_auditlog).

    Как и ``apps.mail.models.AuditLog``: заведена здесь для паритета схемы
    (DoD п.2 брифа). Единственный писатель исходника
    (``app/api/v1/read.py::mark_read`` -> ``record_action(session, user_id,
    "mark_read", "RoomParticipant", f"{room_id}/{message_id}")``) вызывает
    ``services/audit.py::record_action`` ПОЗИЦИОННЫМИ аргументами против её
    же сигнатуры (``record_action(session, *, user_id, action,
    resource_type, resource_id=None, ...)`` — keyword-only после
    ``session``) -> вызов падает ``TypeError`` при фактическом исполнении.

    Хуже того: сам ``read.py``-роут зарегистрирован на ТОТ ЖЕ итоговый путь
    и метод, что и ``messages.py::mark_message_read`` (``app/main.py``:
    ``messages_router`` смонтирован под ``prefix="/api/messenger/v1/
    messages"`` с путём ``"/room/{room_id}/read/{message_id}"``;
    ``read_router`` — под ``prefix="/api/messenger/v1"`` с путём
    ``"/messages/room/{room_id}/read/{message_id}"`` — идентичный итоговый
    URL), причём зарегистрирован ПОСЛЕ него. Starlette матчит первый
    зарегистрированный роут -> ``read.py::mark_read`` МЁРТВ, никогда не
    вызывается в реальном сервисе (двойная причина: и unreachable route, и
    сломанный вызов, если бы он вдруг стал достижим).

    Перенесённая логика (``apps/messenger/views.py::mark_message_read``)
    воспроизводит РЕАЛЬНО достижимую ветку (``messages.py``), БЕЗ
    audit-записи — так же, как и в исходнике (``messages.py`` эту таблицу
    не трогает вовсе)."""

    user_id = models.IntegerField(null=True, blank=True, db_index=True)
    action = models.CharField(max_length=100, db_index=True)
    resource_type = models.CharField(max_length=100)
    resource_id = models.CharField(max_length=100, null=True, blank=True, db_index=True)
    changes = models.JSONField(null=True, blank=True)
    ip_address = models.CharField(max_length=45, null=True, blank=True)
    user_agent = models.TextField(null=True, blank=True)
    correlation_id = models.CharField(max_length=36, null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(db_default=Now(), db_index=True)

    def __str__(self) -> str:
        return f"<AuditLog(id={self.id}, action={self.action!r})>"
