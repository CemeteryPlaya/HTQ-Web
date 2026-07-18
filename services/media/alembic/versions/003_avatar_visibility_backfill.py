"""Mark existing avatar files as public.

Revision ID: 0003_avatar_visibility
Revises: 0002_audit_log
Create Date: 2026-05-05 00:00:00.000000

Root-cause fix for "uploaded avatars are 401 in the browser":

Avatars are referenced by ``auth.users.avatar_url`` and rendered by the
frontend with a plain ``<img src="/api/media/v1/files/{id}">`` tag. The
``<img>`` element does not carry the JWT, so a private file (the historical
default) returns 401 and the avatar never appears.

Going forward the user-service uploads avatars with ``scope=avatar`` and the
media-service forces ``is_public=True`` for that scope. This migration
backfills the existing avatar rows so previously uploaded pictures become
visible without re-uploading.

Cross-schema UPDATE is intentional: we read ``auth.users.avatar_url`` and
update ``media.file_metadata`` in the same Postgres instance. This is a
one-time data fix that cannot be expressed inside a single service alone.
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0003_avatar_visibility"
down_revision: Union[str, None] = "0002_audit_log"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # The user-service ``users`` table lives in the ``public`` schema (not
    # ``auth``, despite the conceptual name). Probe both so the migration
    # works in legacy and current layouts; skip silently if neither exists.
    bind = op.get_bind()
    users_table = bind.exec_driver_sql(
        "SELECT COALESCE(to_regclass('public.users'), to_regclass('auth.users'))::text"
    ).scalar()
    if not users_table:
        return

    op.execute(
        f"""
        UPDATE media.file_metadata AS fm
           SET is_public = TRUE
         WHERE fm.id::text IN (
             SELECT regexp_replace(u.avatar_url, '^.*/files/([0-9a-f-]{{36}}).*$', '\\1')
               FROM {users_table} AS u
              WHERE u.avatar_url IS NOT NULL
                AND u.avatar_url ~ '/files/[0-9a-f-]{{36}}'
         )
           AND fm.is_public = FALSE
        """
    )


def downgrade() -> None:
    # Intentionally no-op: we cannot tell which rows were flipped by this
    # migration vs. legitimately-public uploads after the fact, and reverting
    # would re-introduce the 401 bug.
    pass
