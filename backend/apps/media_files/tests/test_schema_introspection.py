"""Schema-introspection tests for the ``media_files`` app's idiomatic Django
models.

Mirrors ``apps/cms/tests/test_schema_introspection.py`` and
``apps/users/tests/test_schema_introspection.py``. Task 3.1 ports the
FastAPI ``media`` microservice's three tables (``file_metadata``,
``file_variants``, ``audit_log``) into idiomatic Django from scratch —
default ``public`` schema, Django-generated names, ``TextChoices`` instead
of a database enum type (the FastAPI source used plain ``String`` columns
for its enum-ish fields anyway, so there is no PG enum to prove absent here,
unlike cms's ``news_status``).
"""

import pytest

from django.db import connection

from apps.media_files import models


def _fetchall(sql, params=None):
    with connection.cursor() as cursor:
        cursor.execute(sql, params or [])
        return cursor.fetchall()


# Every column that carries ``db_default=`` on the model must have a real
# DB-level DEFAULT — not just a Django-application-side ``default=`` — so
# that a direct INSERT bypassing the ORM still gets a sane value.
COLUMNS_REQUIRING_DB_DEFAULT = [
    ("media_files_filemetadata", "original_filename"),
    ("media_files_filemetadata", "size"),
    ("media_files_filemetadata", "mime"),
    ("media_files_filemetadata", "storage_backend"),
    ("media_files_filemetadata", "is_public"),
    ("media_files_filemetadata", "kind"),
    ("media_files_filemetadata", "scope"),
    ("media_files_filemetadata", "created_at"),
    ("media_files_filemetadata", "updated_at"),
    ("media_files_filevariant", "size"),
    ("media_files_filevariant", "created_at"),
    ("media_files_auditlog", "created_at"),
]


@pytest.mark.django_db
def test_columns_have_db_level_defaults():
    rows = _fetchall(
        """
        SELECT table_name, column_name, column_default
        FROM information_schema.columns
        WHERE table_schema = 'public'
        """
    )
    defaults = {(t, c): d for t, c, d in rows}

    missing = [
        (table, column)
        for table, column in COLUMNS_REQUIRING_DB_DEFAULT
        if defaults.get((table, column)) is None
    ]
    assert missing == [], (
        f"columns missing a DB-level default (column_default IS NULL): {missing}"
    )


@pytest.mark.django_db
def test_media_files_tables_exist_in_public_schema():
    rows = _fetchall(
        """
        SELECT table_name FROM information_schema.tables
        WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
        """
    )
    existing = {r[0] for r in rows}
    expected = {
        "media_files_filemetadata",
        "media_files_filevariant",
        "media_files_auditlog",
    }
    missing = expected - existing
    assert missing == set(), f"expected media_files tables missing from public schema: {missing}"

    # No leftover dedicated `media` Postgres schema.
    schema_rows = _fetchall(
        "SELECT schema_name FROM information_schema.schemata WHERE schema_name = 'media'"
    )
    assert schema_rows == [], "a dedicated `media` Postgres schema should no longer exist"


@pytest.mark.django_db
def test_indexed_columns_have_indexes():
    """FastAPI source had explicit ``index=True`` on these columns — a
    phase-1 review caught 11 silently dropped indexes on an earlier app, so
    this list is asserted explicitly rather than trusted by inspection."""
    for table, column in [
        ("media_files_filemetadata", "owner_id"),
        ("media_files_filemetadata", "sha256"),
        ("media_files_filemetadata", "kind"),
        ("media_files_filemetadata", "scope"),
        ("media_files_filemetadata", "deleted_at"),
        ("media_files_filemetadata", "created_at"),
        ("media_files_filemetadata", "path"),  # unique=True
        ("media_files_filevariant", "file_id"),  # FK auto-indexed
        ("media_files_filevariant", "path"),  # unique=True
        ("media_files_auditlog", "user_id"),
        ("media_files_auditlog", "action"),
        ("media_files_auditlog", "resource_id"),
        ("media_files_auditlog", "correlation_id"),
        ("media_files_auditlog", "created_at"),
    ]:
        rows = _fetchall(
            """
            SELECT indexdef FROM pg_indexes
            WHERE schemaname = 'public' AND tablename = %s
            """,
            [table],
        )
        assert any(column in r[0] for r in rows), (
            f"{table}.{column} should be backed by an index"
        )


@pytest.mark.django_db
def test_file_variant_unique_constraint_on_file_and_variant():
    rows = _fetchall(
        """
        SELECT indexdef FROM pg_indexes
        WHERE schemaname = 'public' AND tablename = 'media_files_filevariant'
        """
    )
    assert any(
        "UNIQUE" in r[0] and "file_id" in r[0] and "variant" in r[0] for r in rows
    ), "(file_id, variant) should be backed by a unique index"


def test_file_variant_fk_is_cascade():
    import django.db.models.deletion as deletion

    field = models.FileVariant._meta.get_field("file")
    assert field.remote_field.on_delete is deletion.CASCADE


@pytest.mark.django_db
def test_file_variant_cascade_deletes_with_file_metadata():
    meta = models.FileMetadata.objects.create(path="chat/orig.jpg", mime="image/jpeg")
    variant = models.FileVariant.objects.create(
        file=meta, variant="thumb_256", path="chat/orig.thumb_256.jpg",
        mime="image/jpeg", width=256, height=256,
    )
    variant_id = variant.id

    meta.delete()

    assert not models.FileVariant.objects.filter(id=variant_id).exists()


def test_kind_scope_storage_backend_are_plain_varchar_no_pg_enum():
    """No PostgreSQL enum type — idiomatic ``CharField`` + Python-side
    ``TextChoices``, matching the FastAPI source (which already used plain
    ``String`` columns, not a PG enum, for these fields)."""
    kind_field = models.FileMetadata._meta.get_field("kind")
    scope_field = models.FileMetadata._meta.get_field("scope")
    storage_field = models.FileMetadata._meta.get_field("storage_backend")
    path_field = models.FileMetadata._meta.get_field("path")

    assert isinstance(kind_field, type(path_field))  # both CharField
    assert isinstance(scope_field, type(path_field))
    assert isinstance(storage_field, type(path_field))

    assert kind_field.max_length == 16
    assert kind_field.default == models.FileKind.OTHER
    assert set(models.FileKind.values) == {"image", "video", "audio", "document", "other"}

    assert scope_field.max_length == 32
    assert scope_field.default == models.FileScope.GENERIC
    assert set(models.FileScope.values) == {
        "avatar", "news", "chat", "hr_doc", "hr_department", "task_attachment", "generic",
    }

    assert storage_field.max_length == 16
    assert storage_field.default == models.StorageBackend.LOCAL
    assert set(models.StorageBackend.values) == {"local", "s3"}


@pytest.mark.django_db
def test_no_media_enum_pg_types_exist():
    for typname in ("filekind", "file_kind", "filescope", "file_scope",
                    "storagebackend", "storage_backend"):
        rows = _fetchall("SELECT 1 FROM pg_type WHERE typname = %s", [typname])
        assert rows == [], f"no PG enum type named {typname!r} should exist"
