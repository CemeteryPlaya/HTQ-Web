"""Schema-introspection tests for the ``users`` app's idiomatic Django models.

Mirrors ``apps/cms/tests/test_schema_introspection.py``. Task 2.1 rewrote
``apps.users`` from scratch: dropped ``PermissionsMixin`` (customer decision
Р1 — Django groups/permissions are not used; RBAC lives in
``htqweb.authn``), removed the ``db_table = "users"`` override so tables use
Django's own default naming (``users_user`` / ``users_item``), and applied
the project's ``db_default=``/``db_index=True`` idioms established by the
cms pilot.
"""

import pytest

from django.db import connection

from apps.users import models


def _fetchall(sql, params=None):
    with connection.cursor() as cursor:
        cursor.execute(sql, params or [])
        return cursor.fetchall()


# Every column that carries ``db_default=`` on the model must have a real
# DB-level DEFAULT — not just a Django-application-side ``default=`` — so
# that a direct INSERT bypassing the ORM still gets a sane value.
COLUMNS_REQUIRING_DB_DEFAULT = [
    ("users_user", "first_name"),
    ("users_user", "last_name"),
    ("users_user", "patronymic"),
    ("users_user", "display_name"),
    ("users_user", "bio"),
    ("users_user", "phone"),
    ("users_user", "status"),
    ("users_user", "is_staff"),
    ("users_user", "is_superuser"),
    ("users_user", "must_change_password"),
    ("users_user", "date_joined"),
    ("users_user", "created_at"),
    ("users_user", "updated_at"),
    ("users_auditlog", "created_at"),
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
def test_users_tables_exist_in_public_schema_with_django_default_names():
    rows = _fetchall(
        """
        SELECT table_name FROM information_schema.tables
        WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
        """
    )
    existing = {r[0] for r in rows}
    assert {"users_user", "users_auditlog"} <= existing
    # The old FastAPI-parity `users`/`items` table names must be gone.
    assert "users" not in existing
    assert "items" not in existing


@pytest.mark.django_db
def test_no_permissionsmixin_join_tables_exist():
    """Р1: Django groups/permissions are not used — proves PermissionsMixin
    was actually dropped, not just hidden."""
    rows = _fetchall(
        """
        SELECT table_name FROM information_schema.tables
        WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
        """
    )
    existing = {r[0] for r in rows}
    assert "users_user_groups" not in existing
    assert "users_user_user_permissions" not in existing


def test_user_status_is_plain_varchar_no_pg_enum():
    field = models.User._meta.get_field("status")
    assert isinstance(field, type(models.User._meta.get_field("username")))  # both CharField
    assert field.max_length == 16
    assert field.default == models.UserStatus.PENDING
    assert set(models.UserStatus.values) == {"pending", "active", "suspended", "rejected"}


@pytest.mark.django_db
def test_no_users_status_pg_enum_exists():
    rows = _fetchall("SELECT 1 FROM pg_type WHERE typname = 'userstatus'")
    assert rows == []
    rows = _fetchall("SELECT 1 FROM pg_type WHERE typname = 'user_status'")
    assert rows == []


@pytest.mark.django_db
def test_indexed_columns_have_indexes():
    """FastAPI source (services/user/app/models/user.py) had an explicit
    Index on status; username/email get theirs for free via unique=True."""
    for table, column in [
        ("users_user", "username"),
        ("users_user", "email"),
        ("users_user", "status"),
        ("users_auditlog", "user_id"),
        ("users_auditlog", "action"),
        ("users_auditlog", "resource_id"),
        ("users_auditlog", "correlation_id"),
        ("users_auditlog", "created_at"),
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


