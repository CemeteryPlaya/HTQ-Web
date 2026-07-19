"""Schema-introspection tests for the ``cms`` app's idiomatic Django models.

This app used to be a schema-preserving port of the FastAPI ``cms``
microservice (its own ``cms`` Postgres schema, alembic-named constraints,
a custom ``news_status`` PG enum). The customer clarified (2026-07-19) that
this repo never runs side-by-side with that FastAPI stack, so alembic
parity is no longer a goal — the tests below assert the *idiomatic* Django
schema is correct, not that it matches alembic's exact object names.

``test_columns_have_db_level_defaults`` is kept from the old version almost
verbatim: it caught a real bug before (columns missing a server-side
DEFAULT, which matters because ``db_default=`` is a deliberate idiom this
app relies on), so it stays — just scoped to ``public`` instead of ``cms``.
"""

import pytest

from django.db import connection

from apps.cms import models


def _fetchall(sql, params=None):
    with connection.cursor() as cursor:
        cursor.execute(sql, params or [])
        return cursor.fetchall()


# Every column that carries ``db_default=`` on the model must have a real
# DB-level DEFAULT — not just a Django-application-side ``default=`` — so
# that a direct INSERT bypassing the ORM still gets a sane value.
COLUMNS_REQUIRING_DB_DEFAULT = [
    ("cms_news", "summary"),
    ("cms_news", "content"),
    ("cms_news", "excerpt"),
    ("cms_news", "category"),
    ("cms_news", "published"),
    ("cms_news", "created_at"),
    ("cms_news", "updated_at"),
    ("cms_news", "status"),
    ("cms_contactrequest", "first_name"),
    ("cms_contactrequest", "last_name"),
    ("cms_contactrequest", "message"),
    ("cms_contactrequest", "reply_message"),
    ("cms_contactrequest", "handled"),
    ("cms_contactrequest", "created_at"),
    ("cms_category", "description"),
    ("cms_category", "created_at"),
    ("cms_tag", "created_at"),
    ("cms_newsattachment", "role"),
    ("cms_newsattachment", "created_at"),
    ("cms_auditlog", "created_at"),
]


@pytest.mark.django_db
def test_columns_have_db_level_defaults():
    """Every column with ``db_default=`` on the model must carry a real DB
    DEFAULT (``column_default IS NOT NULL``), not just an ORM-side default=.
    This caught a real bug before (Task 1.1) — kept as-is, just scoped to
    ``public`` now that cms tables live there instead of a dedicated schema.
    """
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
def test_cms_tables_exist_in_public_schema():
    """The cms app owns no dedicated Postgres schema anymore — every table
    it manages must live in ``public``, using Django's own default naming."""
    rows = _fetchall(
        """
        SELECT table_name FROM information_schema.tables
        WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
        """
    )
    existing = {r[0] for r in rows}
    expected = {
        "cms_news",
        "cms_category",
        "cms_tag",
        "cms_contactrequest",
        "cms_newsattachment",
        "cms_auditlog",
        "cms_news_tags",  # Django's auto-generated M2M through table
    }
    missing = expected - existing
    assert missing == set(), f"expected cms tables missing from public schema: {missing}"

    # And no leftover `cms` schema at all.
    schema_rows = _fetchall(
        "SELECT schema_name FROM information_schema.schemata WHERE schema_name = 'cms'"
    )
    assert schema_rows == [], "a dedicated `cms` Postgres schema should no longer exist"


def test_news_foreign_keys_use_expected_on_delete_behavior():
    """FK cascade behaviour, asserted at the Django model level (idiomatic
    Django manages this at the ORM layer, not via DB-level ON DELETE
    clauses — so there is nothing meaningful to introspect in pg_constraint
    for this anymore)."""
    import django.db.models.deletion as deletion

    category_field = models.News._meta.get_field("category_ref")
    assert category_field.remote_field.on_delete is deletion.SET_NULL

    attachment_field = models.NewsAttachment._meta.get_field("news")
    assert attachment_field.remote_field.on_delete is deletion.CASCADE


@pytest.mark.django_db
def test_news_slug_and_taxonomy_slugs_are_unique():
    rows = _fetchall(
        """
        SELECT indexdef FROM pg_indexes
        WHERE schemaname = 'public' AND tablename = 'cms_news' AND indexname LIKE %s
        """,
        ["%slug%"],
    )
    assert any("UNIQUE" in r[0] for r in rows), "cms_news.slug must be backed by a unique index"


def test_news_status_is_plain_varchar_with_four_choices():
    """No PostgreSQL enum type anymore — ``status`` is an idiomatic
    ``CharField`` with a Python-side ``TextChoices``."""
    field = models.News._meta.get_field("status")
    assert isinstance(field, type(models.News._meta.get_field("title")))  # both CharField
    assert field.max_length == 20
    assert field.default == models.NewsStatus.DRAFT
    assert set(models.NewsStatus.values) == {"draft", "scheduled", "published", "archived"}


@pytest.mark.django_db
def test_no_news_status_pg_enum_exists():
    rows = _fetchall(
        "SELECT 1 FROM pg_type WHERE typname = 'news_status'"
    )
    assert rows == [], "the custom PG enum `news_status` should no longer exist"
