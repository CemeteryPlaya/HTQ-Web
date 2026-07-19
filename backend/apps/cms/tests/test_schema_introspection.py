"""Schema-introspection tests for the ``cms`` Django migration port.

test_models_mapping.py only checks ORM-level facts (``managed``, one
``db_table`` string, one round-trip) — none of that would have caught the
Task 1.1 review findings (missing server-side ``DEFAULT``s, invented FK
names, an extra ``pg_constraint`` row on the slug index). These tests query
the *actually built* Postgres schema via ``information_schema`` / ``pg_catalog``
so a regression in any of those areas fails a test, not just a live INSERT.

This file is the template other domain apps should copy.
"""

import pytest

from django.db import connection


def _fetchall(sql, params=None):
    with connection.cursor() as cursor:
        cursor.execute(sql, params or [])
        return cursor.fetchall()


# Finding 1 — every column alembic gave a server_default must have a
# non-null column_default in the built schema (table, column).
COLUMNS_REQUIRING_DB_DEFAULT = [
    ("news", "summary"),
    ("news", "content"),
    ("news", "excerpt"),
    ("news", "category"),
    ("news", "published"),
    ("news", "created_at"),
    ("news", "updated_at"),
    ("news", "status"),  # already present pre-fix; kept for completeness
    ("contact_requests", "first_name"),
    ("contact_requests", "last_name"),
    ("contact_requests", "message"),
    ("contact_requests", "reply_message"),
    ("contact_requests", "handled"),
    ("contact_requests", "created_at"),
    ("categories", "description"),
    ("categories", "created_at"),
    ("tags", "created_at"),
    ("news_attachments", "role"),
    ("news_attachments", "created_at"),
    ("audit_log", "created_at"),
]

# Finding 2 — FK constraint names Postgres assigns by default
# (`<table>_<column>_fkey`) for the alembic FKs left unnamed, plus the one
# alembic names explicitly (fk_cms_news_category).
EXPECTED_FOREIGN_KEYS = [
    # (constraint name, table, referenced table, delete rule: c=cascade, n=set null)
    ("fk_cms_news_category", "news", "categories", "n"),
    ("news_attachments_news_id_fkey", "news_attachments", "news", "c"),
    ("news_tags_news_id_fkey", "news_tags", "news", "c"),
    ("news_tags_tag_id_fkey", "news_tags", "tags", "c"),
]

EXPECTED_INDEXES = [
    "ix_cms_contact_requests_created_at",
    "ix_cms_contact_requests_handled",
    "ix_cms_contact_requests_replied_at",
    "ix_cms_audit_log_user_id",
    "ix_cms_audit_log_action",
    "ix_cms_audit_log_resource_id",
    "ix_cms_audit_log_created_at",
    "ix_cms_audit_log_correlation_id",
    "ix_cms_categories_slug",
    "ix_cms_news_category",
    "ix_cms_news_created_at",
    "ix_cms_news_published",
    "ix_cms_news_published_at",
    "ix_cms_news_status",
    "ix_cms_news_scheduled_at",
    "ix_cms_news_category_id",
    "ix_cms_news_author_id",
    "ix_cms_news_slug",
    "ix_cms_news_attachments_news_id",
    "ix_cms_tags_slug",
    "ix_cms_news_tags_tag_id",
]


@pytest.mark.django_db
def test_columns_have_db_level_defaults():
    """Every column alembic gave server_default= must carry a real DB
    DEFAULT, not just a Django-application-side default= — otherwise the
    still-running FastAPI cms service (which omits these columns from its
    INSERTs) raises NotNullViolation against a Django-built schema."""
    rows = _fetchall(
        """
        SELECT table_name, column_name, column_default
        FROM information_schema.columns
        WHERE table_schema = 'cms'
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
def test_foreign_key_names_and_delete_rules():
    """FK constraint names must be copied from what Postgres actually
    assigns (or what alembic names explicitly), never invented — and the
    ON DELETE rule must match alembic's."""
    rows = _fetchall(
        """
        SELECT
            conname,
            conrelid::regclass::text AS table_name,
            confrelid::regclass::text AS ref_table,
            confdeltype
        FROM pg_constraint
        WHERE connamespace = 'cms'::regnamespace AND contype = 'f'
        """
    )
    by_name = {name: (table, ref, deltype) for name, table, ref, deltype in rows}

    for name, table, ref_table, deltype in EXPECTED_FOREIGN_KEYS:
        assert name in by_name, f"FK constraint {name!r} not found in cms schema"
        actual_table, actual_ref, actual_deltype = by_name[name]
        assert actual_table == f"cms.{table}", (name, actual_table)
        assert actual_ref == f"cms.{ref_table}", (name, actual_ref)
        assert actual_deltype == deltype, (name, actual_deltype)


@pytest.mark.django_db
def test_expected_indexes_exist():
    rows = _fetchall(
        "SELECT indexname FROM pg_indexes WHERE schemaname = 'cms'"
    )
    existing = {r[0] for r in rows}
    missing = [name for name in EXPECTED_INDEXES if name not in existing]
    assert missing == [], f"expected indexes missing from cms schema: {missing}"


@pytest.mark.django_db
def test_news_slug_unique_index_has_no_constraint_row():
    """ix_cms_news_slug must be a bare unique index (alembic's
    create_index(..., unique=True)) — NOT a UniqueConstraint, which would
    add an extra pg_constraint row (contype='u') alembic never created."""
    rows = _fetchall(
        """
        SELECT indexname FROM pg_indexes
        WHERE schemaname = 'cms' AND indexname = 'ix_cms_news_slug'
        """
    )
    assert len(rows) == 1, "ix_cms_news_slug index must exist exactly once"

    rows = _fetchall(
        """
        SELECT count(*) FROM pg_constraint
        WHERE connamespace = 'cms'::regnamespace AND conname = 'ix_cms_news_slug'
        """
    )
    assert rows[0][0] == 0, (
        "ix_cms_news_slug must not have a pg_constraint row "
        "(it must be a bare index, not a UniqueConstraint)"
    )


@pytest.mark.django_db
def test_news_status_enum_labels_in_order():
    rows = _fetchall(
        """
        SELECT enumlabel FROM pg_enum
        WHERE enumtypid = (
            SELECT oid FROM pg_type
            WHERE typname = 'news_status' AND typnamespace = 'cms'::regnamespace
        )
        ORDER BY enumsortorder
        """
    )
    labels = [r[0] for r in rows]
    assert labels == ["draft", "scheduled", "published", "archived"]
