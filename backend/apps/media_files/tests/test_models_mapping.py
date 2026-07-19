import pytest

from apps.media_files import models


def test_media_files_models_own_their_schema():
    """Django владеет схемой: идиоматичные Django-модели, без FastAPI-схем."""
    for model in (models.FileMetadata, models.FileVariant, models.AuditLog):
        assert model._meta.managed is True, model.__name__


def test_tables_use_idiomatic_django_names():
    # public-схема, стандартные имена Django (не 'media"."file_metadata' из
    # FastAPI-порта).
    assert models.FileMetadata._meta.db_table == "media_files_filemetadata"
    assert models.FileVariant._meta.db_table == "media_files_filevariant"
    assert models.AuditLog._meta.db_table == "media_files_auditlog"


@pytest.mark.django_db
def test_file_metadata_roundtrip_uses_real_column_names():
    meta = models.FileMetadata.objects.create(
        path="avatars/1/abc.png",
        original_filename="abc.png",
        owner_id=1,
        size=1234,
        mime="image/png",
        is_public=True,
        kind=models.FileKind.IMAGE,
        scope=models.FileScope.AVATAR,
        width=256,
        height=256,
    )
    meta.refresh_from_db()
    assert meta.path == "avatars/1/abc.png"
    assert meta.kind == "image"
    assert meta.scope == "avatar"
    assert meta.storage_backend == "local"
    assert meta.is_public is True


@pytest.mark.django_db
def test_file_metadata_id_is_uuid_not_int():
    import uuid

    meta = models.FileMetadata.objects.create(path="x/y.png")
    assert isinstance(meta.id, uuid.UUID)


@pytest.mark.django_db
def test_file_metadata_defaults():
    meta = models.FileMetadata.objects.create(path="generic/z.bin")
    meta.refresh_from_db()
    assert meta.original_filename == ""
    assert meta.size == 0
    assert meta.mime == "application/octet-stream"
    assert meta.storage_backend == "local"
    assert meta.is_public is False
    assert meta.kind == "other"
    assert meta.scope == "generic"
    assert meta.sha256 is None
    assert meta.width is None
    assert meta.height is None
    assert meta.deleted_at is None


@pytest.mark.django_db
def test_file_variant_roundtrip_and_fk():
    meta = models.FileMetadata.objects.create(path="news/orig.jpg", mime="image/jpeg")
    variant = models.FileVariant.objects.create(
        file=meta,
        variant="thumb_256",
        path="news/orig.thumb_256.jpg",
        mime="image/jpeg",
        width=256,
        height=256,
    )
    variant.refresh_from_db()
    assert variant.file_id == meta.id
    assert variant.variant == "thumb_256"
    assert variant.size == 0
    assert meta.variants.count() == 1


@pytest.mark.django_db
def test_audit_log_roundtrip():
    entry = models.AuditLog.objects.create(
        user_id=1,
        action="file.upload",
        resource_type="file_metadata",
        resource_id="abc-123",
        changes={"is_public": True},
    )
    entry.refresh_from_db()
    assert entry.action == "file.upload"
    assert entry.changes == {"is_public": True}
