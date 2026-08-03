"""Media domain models — idiomatic Django, built from scratch in the default
``public`` schema.

Ported from the FastAPI ``media`` microservice
(``services/media/app/models/{file_metadata,file_variant,audit_log}.py``,
``app/models/base.py`` for the timestamp mixin). Per the customer's
2026-07-19 clarification (see ``apps/cms/models.py`` for the fuller note),
this repo is a standalone copy that never runs side-by-side with the live
FastAPI stack — there is no reason to preserve FastAPI-specific schema
details (its own ``media`` Postgres schema, alembic-named constraints,
zero PG enum types anyway — the source already used plain ``String``
columns for its enum-ish fields). The models below are plain, idiomatic
Django: default ``public`` schema, Django-generated table/constraint/index
names, and ``TextChoices`` for the enum-ish columns (``kind``, ``scope``,
``storage_backend``).

The app is named ``media_files`` (not ``media``) to avoid colliding with
Django's ``MEDIA_*`` settings conventions; the service-registry name is
still ``media`` (see ``htqweb.middleware.service_gate.APP_LABEL_TO_SERVICE``).

``db_default=`` is added to every column that carries a concrete scalar
default in the FastAPI source (matching the cms/users pilots' idiom), even
where the source only had an SQLAlchemy application-side ``default=`` and no
``server_default`` — a real DB-level default is the project's convention
now, not alembic parity.
"""

import uuid

from django.db import models
from django.db.models.functions import Now


class FileKind(models.TextChoices):
    """Mirrors ``kind_from_mime()`` in
    ``services/media/app/services/image_service.py``."""

    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"
    DOCUMENT = "document"
    OTHER = "other"


class FileScope(models.TextChoices):
    """Mirrors ``KNOWN_SCOPES`` in
    ``services/media/app/core/scope_policy.py``."""

    AVATAR = "avatar"
    NEWS = "news"
    CHAT = "chat"
    HR_DOC = "hr_doc"
    HR_DEPARTMENT = "hr_department"
    TASK_ATTACHMENT = "task_attachment"
    GENERIC = "generic"


class StorageBackend(models.TextChoices):
    """Mirrors ``storage_backend: str = "local"  # local | s3`` in
    ``services/media/app/core/settings.py``."""

    LOCAL = "local"
    S3 = "s3"


class FileMetadata(models.Model):
    """Port of ``services/media/app/models/file_metadata.py``.

    UUID primary key (not the Django default AutoField) — matches the
    source's ``id: Mapped[uuid.UUID] = mapped_column(..., primary_key=True,
    default=uuid.uuid4)``.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    path = models.CharField(max_length=1024, unique=True)
    original_filename = models.CharField(max_length=512, default="", blank=True, db_default="")
    owner_id = models.IntegerField(null=True, blank=True, db_index=True)
    size = models.BigIntegerField(default=0, db_default=0)
    mime = models.CharField(
        max_length=255, default="application/octet-stream", blank=True,
        db_default="application/octet-stream",
    )
    storage_backend = models.CharField(
        max_length=16, choices=StorageBackend.choices, default=StorageBackend.LOCAL,
        db_default=StorageBackend.LOCAL,
    )
    is_public = models.BooleanField(default=False, db_default=False)

    # Phase 1 (FastAPI source): classification + integrity
    sha256 = models.CharField(max_length=64, null=True, blank=True, db_index=True)
    kind = models.CharField(
        max_length=16, choices=FileKind.choices, default=FileKind.OTHER,
        db_default=FileKind.OTHER, db_index=True,
    )
    scope = models.CharField(
        max_length=32, choices=FileScope.choices, default=FileScope.GENERIC,
        db_default=FileScope.GENERIC, db_index=True,
    )
    width = models.IntegerField(null=True, blank=True)
    height = models.IntegerField(null=True, blank=True)
    deleted_at = models.DateTimeField(null=True, blank=True, db_index=True)

    created_at = models.DateTimeField(auto_now_add=True, db_default=Now(), db_index=True)
    updated_at = models.DateTimeField(auto_now=True, db_default=Now())

    class Meta:
        verbose_name = "Файл"
        verbose_name_plural = "Файлы"

    def __repr__(self) -> str:  # pragma: no cover
        return f"<FileMetadata id={self.id} path={self.path!r} size={self.size}>"


class FileVariant(models.Model):
    """Port of ``services/media/app/models/file_variant.py`` — derived
    renditions (thumbnails, previews) of an original file.

    ``file`` FK is CASCADE, matching the source's
    ``ForeignKey("media.file_metadata.id", ondelete="CASCADE")`` — deleting
    a FileMetadata drops its variants along with it. Django auto-indexes FK
    columns, so no redundant ``db_index=True`` on ``file``.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    file = models.ForeignKey(FileMetadata, on_delete=models.CASCADE, related_name="variants")
    variant = models.CharField(max_length=16)
    path = models.CharField(max_length=1024, unique=True)
    size = models.BigIntegerField(default=0, db_default=0)
    mime = models.CharField(max_length=255)
    width = models.IntegerField()
    height = models.IntegerField()
    created_at = models.DateTimeField(auto_now_add=True, db_default=Now())

    class Meta:
        verbose_name = "Вариант файла"
        verbose_name_plural = "Варианты файлов"
        constraints = [
            models.UniqueConstraint(fields=["file", "variant"], name="unique_file_variant"),
        ]

    def __repr__(self) -> str:  # pragma: no cover
        return f"<FileVariant file_id={self.file_id} variant={self.variant!r} {self.width}x{self.height}>"


class AuditLog(models.Model):
    """Port of ``services/media/app/models/audit_log.py`` — per-app audit
    trail of privileged actions, same shape as ``apps.cms.models.AuditLog``
    (each app owns its own concrete AuditLog rather than sharing one)."""

    user_id = models.IntegerField(null=True, blank=True, db_index=True)
    action = models.CharField(max_length=100, db_index=True)
    resource_type = models.CharField(max_length=100)
    resource_id = models.CharField(max_length=100, null=True, blank=True, db_index=True)
    changes = models.JSONField(null=True, blank=True)
    ip_address = models.CharField(max_length=45, null=True, blank=True)
    user_agent = models.TextField(null=True, blank=True)
    correlation_id = models.CharField(max_length=36, null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True, db_default=Now())

    class Meta:
        verbose_name = "Запись аудита"
        verbose_name_plural = "Журнал аудита"
