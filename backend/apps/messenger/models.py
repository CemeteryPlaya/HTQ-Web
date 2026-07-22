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

``ChatAttachment``/``UserKey`` (attachments/keys под-задача, PLAN.md §6.5) —
портированы ниже. Байты вложений хранятся В apps.media_files (через
``apps.media_files.interface`` — межаппные FK запрещены, см.
apps/core/tests/test_app_isolation.py), НЕ в этой аппке напрямую — тот же
принцип, что ``apps.hr.models.DepartmentFile``/``apps.mail.models.
EmailAttachment``. Подробности сверки полей/дизайна — докстринг
``ChatAttachment`` ниже и ``apps/messenger/services/attachment_service.py``.
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


class ChatAttachmentDataType(models.TextChoices):
    """Порт классификации ``services/messenger/app/services/
    attachment_storage.py::classify_attachment`` — исходная колонка
    (``String(40)``) НЕ несёт CheckConstraint на это множество (тот же
    принцип, что ``RoomType``/``RoomParticipantRole`` выше), choices здесь
    чисто для админки/документации."""

    IMAGES = "images", "Изображения"
    AUDIO = "audio", "Аудио"
    VIDEO = "video", "Видео"
    ARCHIVES = "archives", "Архивы"
    DOCUMENTS = "documents", "Документы"
    OTHER = "other", "Другое"


class ChatAttachment(models.Model):
    """Порт ``services/messenger/app/models/domain.py::ChatAttachment``
    (attachments/keys под-задача).

    Р3 (media.interface, decision — attachments-brief п.4): исходник хранил
    байты сам (``app/services/{attachment_storage,s3_storage}.py`` — S3 PUT
    напрямую), с ``storage_path``/``public_url`` как raw S3-ключ/подписанный
    URL, и НИКОГДА не заполнял свою же ``file_metadata_id`` (модель несёт
    комментарий "Refers to media-service if used" — мёртвая, forward-looking
    колонка в исходнике). Этот порт наконец включает её: байты идут через
    ``apps.media_files.interface.store_file(scope="chat")`` (Django-монолит —
    сосед по процессу, НЕ отдельный сервис; свой ``s3_storage.py``-клон
    запрещён, см. ``apps/mail/services/attachment_service.py`` докстринг).
    Поля источника сохранены 1:1 по имени/типу/nullable, СЕМАНТИКА трёх из
    них адаптирована под эту межаппную индирекцию (задокументировано на
    каждом поле ниже) — см. ``apps/messenger/services/attachment_service.py``
    для полной картины upload/serve потоков.

    ``message``/``room`` — РЕАЛЬНЫЕ FK (обе модели свои, внутри этой же
    аппки) ``ondelete=CASCADE``, nullable — буквальный порт (исходник:
    ``ForeignKey("messages.id", ondelete="CASCADE")``/``ForeignKey("rooms.id",
    ondelete="CASCADE")``, оба nullable). Django авто-индексирует FK —
    совпадает с исходником (``ix_chat_attachments_message_id``/
    ``ix_chat_attachments_room_id``, обе явные в alembic).

    ``uploaded_by`` — Р2 (тот же принцип, что ``RoomParticipant.user_id``/
    ``Message.sender_id`` в models.py докстринге файла): ГОЛЫЙ
    ``IntegerField`` БЕЗ FK (исходник — ``ForeignKey("chat_user_replicas.id",
    ondelete="CASCADE")``, которой здесь нет). Источник НЕ несёт отдельный
    индекс на этой колонке (``index=True`` отсутствует у ``mapped_column``) —
    здесь тоже нет ``db_index`` (совпадает естественно: обычный
    ``IntegerField` без FK не индексируется по умолчанию).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    message = models.ForeignKey(
        Message, on_delete=models.CASCADE, related_name="attachments", null=True, blank=True,
    )
    room = models.ForeignKey(
        Room, on_delete=models.CASCADE, related_name="attachments", null=True, blank=True,
    )
    # UUID apps.media_files.models.FileMetadata.id ОСНОВНОГО файла — НЕ FK
    # (межаппные FK запрещены). Источник объявлял это же поле, но никогда не
    # заполнял его (см. докстринг класса выше) — здесь это реальная ссылка,
    # заполняемая apps.media_files.interface.store_file().
    file_metadata_id = models.UUIDField(null=True, blank=True)
    filename = models.CharField(max_length=255)
    size = models.IntegerField()
    content_type = models.CharField(max_length=255)
    data_type = models.CharField(
        max_length=40, choices=ChatAttachmentDataType.choices,
        default=ChatAttachmentDataType.OTHER, db_default=ChatAttachmentDataType.OTHER,
    )
    # Р3-адаптация (см. докстринг класса): исходник хранил здесь свой S3-ключ
    # (``chats/<room>/<data_type>/<id>_<filename>``); этот порт хранит
    # ``apps.media_files.models.FileMetadata.path`` (взятое из ответа
    # ``interface.store_file()``) — информационное поле, НЕ читается
    # обратно ни одним путём serve/redirect (те идут через
    # ``interface.get_file_url(file_metadata_id)``, см. attachment_service.py).
    storage_path = models.CharField(max_length=2048, null=True, blank=True)
    # Заполняется ОДИН раз при загрузке (``_public_url`` в
    # attachment_service.py) и НИКОГДА не перечитывается сериализатором
    # (тот же самый "write-only" паритет с исходником: ``ChatAttachmentRead.
    # url`` — computed_field, каждый раз заново подписывающий URL, игнорируя
    # эту сырую колонку — буквальная странность исходника, воспроизведена
    # как есть).
    public_url = models.CharField(max_length=2048, null=True, blank=True)
    # Р3-адаптация (см. докстринг класса): исходник хранил здесь S3-ключ
    # WebP-превью (``image_thumb.py``, ≤256×256, генерируется ТОЛЬКО для
    # ``data_type == "images"``, NULL иначе/при сбое генерации). Этот порт
    # хранит str(UUID) ВТОРОЙ apps.media_files.FileMetadata-строки — превью,
    # загруженное ОТДЕЛЬНЫМ вызовом ``interface.store_file()`` (НЕ через
    # media_files' собственный "variant"-пайплайн: тот кроп квадратный
    # (``image_service.make_variant``, ``square=True``), тогда как контракт
    # чата — превью С СОХРАНЕНИЕМ пропорций, как ``image_thumb.py`` исходника
    # — см. attachment_service.py::make_thumbnail).
    thumbnail_path = models.CharField(max_length=2048, null=True, blank=True)
    # Внутренний размер ОРИГИНАЛА (не превью) — буквальный порт, тот же
    # смысл, что у исходника: UI резервирует aspect-ratio по этим значениям.
    width = models.IntegerField(null=True, blank=True)
    height = models.IntegerField(null=True, blank=True)
    uploaded_by = models.IntegerField()

    created_at = models.DateTimeField(db_default=Now(), db_index=True)
    updated_at = models.DateTimeField(db_default=Now(), auto_now=True)

    @property
    def url(self) -> str | None:
        """Порт ``ChatAttachment.url`` исходника (``return self.public_url``)
        — сырое, потенциально протухшее значение; сериализатор API НЕ
        использует это свойство (см. ``attachment_service.serialize_attachment``,
        который каждый раз заново подписывает через ``attachment_url()``)."""
        return self.public_url

    def __str__(self) -> str:
        return f"<ChatAttachment(id={self.id}, filename={self.filename!r})>"


class UserKey(models.Model):
    """Порт ``services/messenger/app/models/domain.py::UserKey`` — публичные
    ключи для E2EE. Составной PK (``user_id``, ``device_id``) — оба поля
    были ``primary_key=True`` у исходника, без суррогатного id -> Django 5.2
    ``CompositePrimaryKey`` (тот же приём, что ``RoomParticipant`` выше).

    ``user_id`` — Р2: ГОЛЫЙ ``IntegerField`` БЕЗ FK (исходник — ``ForeignKey
    ("chat_user_replicas.id", ondelete="CASCADE")``, которой здесь нет; та
    же логика, что ``RoomParticipant.user_id``/``ChatAttachment.uploaded_by``
    выше) — это платформенный ``apps.users.User.id`` (JWT ``user_id``), а не
    ссылка на реплику.

    ВНИМАНИЕ (админка): как и ``RoomParticipant``, модель с
    ``CompositePrimaryKey`` НЕ регистрируется в apps/messenger/admin.py —
    ``AdminSite.register`` безусловно поднимает ``ImproperlyConfigured`` для
    любой модели с ``_meta.is_composite_pk``.
    """

    user_id = models.IntegerField()
    device_id = models.CharField(max_length=255)
    public_identity_key = models.TextField()
    signed_pre_key = models.TextField()
    signature = models.TextField()

    created_at = models.DateTimeField(db_default=Now(), db_index=True)
    updated_at = models.DateTimeField(db_default=Now(), auto_now=True)

    pk = models.CompositePrimaryKey("user_id", "device_id")

    def __str__(self) -> str:
        return f"<UserKey(user_id={self.user_id}, device_id={self.device_id!r})>"
