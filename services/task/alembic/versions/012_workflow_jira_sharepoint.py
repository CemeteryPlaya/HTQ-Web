"""Rework task workflow to Jira+SharePoint model.

Changes:

1. Status enum expanded from 5 to 7 values:
   - new: backlog, todo, blocked, cancelled
   - removed (mapped): open  -> todo
                       closed -> cancelled
   The PostgreSQL ENUM type ``status`` is rebuilt because PG cannot drop
   enum values in place.

2. ``tasks`` gains ``supervisor_id`` (FK task_users) and
   ``progress_percent`` (smallint 0..100).

3. New tables for the SharePoint side of the model:
   - ``task_assignees``  — M:M task<>user with role (primary/collaborator)
   - ``task_delegates``  — supervisor's deputies (can edit on their behalf)
   - ``task_watchers``   — followers

4. Existing ``tasks.assignee_id`` values are back-filled as ``primary``
   rows in ``task_assignees`` so the source-of-truth (the junction
   table) is consistent with the denormalized column from day one.

Revision ID: 012
Revises: 011
Create Date: 2026-05-22
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "012"
down_revision: Union[str, None] = "011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Status enum rebuild -----------------------------------------------
    # PG does not let you drop enum values in place, and ALTER TYPE ADD
    # VALUE cannot run inside a transaction that also USEs the new value.
    # Solution: build the new enum next to the old one, swap the column
    # type with an explicit CASE map, then drop the old enum.

    op.execute("ALTER TYPE status RENAME TO status_old")
    op.execute(
        "CREATE TYPE status AS ENUM ("
        "'backlog', 'todo', 'in_progress', 'in_review', "
        "'blocked', 'done', 'cancelled')"
    )
    op.execute(
        "ALTER TABLE tasks "
        "ALTER COLUMN status DROP DEFAULT, "
        "ALTER COLUMN status TYPE status USING "
        "CASE status::text "
        "  WHEN 'open' THEN 'todo' "
        "  WHEN 'closed' THEN 'cancelled' "
        "  ELSE status::text "
        "END::status, "
        "ALTER COLUMN status SET DEFAULT 'todo'::status"
    )
    op.execute("DROP TYPE status_old")

    # 2. New columns on tasks ----------------------------------------------

    op.execute(
        "ALTER TABLE tasks "
        "ADD COLUMN IF NOT EXISTS supervisor_id INTEGER "
        "REFERENCES task_users(id) ON DELETE SET NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_tasks_supervisor_id "
        "ON tasks(supervisor_id)"
    )
    op.execute(
        "ALTER TABLE tasks "
        "ADD COLUMN IF NOT EXISTS progress_percent SMALLINT "
        "NOT NULL DEFAULT 0"
    )
    # CHECK constraint added via DO-block since PG has no
    # ``ADD CONSTRAINT IF NOT EXISTS`` syntax.
    op.execute(
        "DO $$ BEGIN "
        "  ALTER TABLE tasks ADD CONSTRAINT ck_tasks_progress_range "
        "  CHECK (progress_percent BETWEEN 0 AND 100); "
        "EXCEPTION WHEN duplicate_object THEN null; END $$;"
    )

    # 3. New role enum + junction tables -----------------------------------

    # Build the enum explicitly with create_type=False so create_table does
    # NOT try to auto-create it (which would clash with our own create), and
    # create it idempotently with checkfirst so re-runs after a partial
    # failure don't blow up on "type already exists".
    role_enum = postgresql.ENUM(
        "primary", "collaborator", name="task_assignee_role", create_type=False
    )
    role_enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "task_assignees",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "task_id",
            sa.Integer(),
            sa.ForeignKey("tasks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("task_users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "role",
            role_enum,
            nullable=False,
            server_default="collaborator",
        ),
        sa.Column(
            "assigned_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("task_id", "user_id", name="uq_task_assignee"),
    )
    op.create_index("ix_task_assignees_task_id", "task_assignees", ["task_id"])
    op.create_index("ix_task_assignees_user_id", "task_assignees", ["user_id"])

    op.create_table(
        "task_delegates",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "task_id",
            sa.Integer(),
            sa.ForeignKey("tasks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("task_users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "granted_by_id",
            sa.Integer(),
            sa.ForeignKey("task_users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "granted_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("task_id", "user_id", name="uq_task_delegate"),
    )
    op.create_index("ix_task_delegates_task_id", "task_delegates", ["task_id"])
    op.create_index("ix_task_delegates_user_id", "task_delegates", ["user_id"])

    op.create_table(
        "task_watchers",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "task_id",
            sa.Integer(),
            sa.ForeignKey("tasks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("task_users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "subscribed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("task_id", "user_id", name="uq_task_watcher"),
    )
    op.create_index("ix_task_watchers_task_id", "task_watchers", ["task_id"])
    op.create_index("ix_task_watchers_user_id", "task_watchers", ["user_id"])

    # 4. Back-fill: every existing assignee becomes a primary row in
    #    task_assignees so the M:M table is the consistent source of truth.
    op.execute(
        "INSERT INTO task_assignees (task_id, user_id, role) "
        "SELECT id, assignee_id, 'primary'::task_assignee_role "
        "FROM tasks "
        "WHERE assignee_id IS NOT NULL "
        "ON CONFLICT (task_id, user_id) DO NOTHING"
    )


def downgrade() -> None:
    op.drop_index("ix_task_watchers_user_id", table_name="task_watchers")
    op.drop_index("ix_task_watchers_task_id", table_name="task_watchers")
    op.drop_table("task_watchers")

    op.drop_index("ix_task_delegates_user_id", table_name="task_delegates")
    op.drop_index("ix_task_delegates_task_id", table_name="task_delegates")
    op.drop_table("task_delegates")

    op.drop_index("ix_task_assignees_user_id", table_name="task_assignees")
    op.drop_index("ix_task_assignees_task_id", table_name="task_assignees")
    op.drop_table("task_assignees")

    op.execute("DROP TYPE IF EXISTS task_assignee_role")

    op.execute(
        "ALTER TABLE tasks DROP CONSTRAINT IF EXISTS ck_tasks_progress_range"
    )
    op.execute("ALTER TABLE tasks DROP COLUMN IF EXISTS progress_percent")
    op.execute("DROP INDEX IF EXISTS ix_tasks_supervisor_id")
    op.execute("ALTER TABLE tasks DROP COLUMN IF EXISTS supervisor_id")

    # Rebuild the legacy 5-value enum.
    op.execute(
        "UPDATE tasks SET status = 'todo'::status WHERE status = 'backlog'::status"
    )
    op.execute(
        "UPDATE tasks SET status = 'in_progress'::status "
        "WHERE status = 'blocked'::status"
    )
    op.execute(
        "UPDATE tasks SET status = 'closed'::status "
        "WHERE status = 'cancelled'::status"
    )

    op.execute("ALTER TYPE status RENAME TO status_new")
    op.execute(
        "CREATE TYPE status AS ENUM ("
        "'open', 'in_progress', 'in_review', 'done', 'closed')"
    )
    op.execute(
        "ALTER TABLE tasks "
        "ALTER COLUMN status DROP DEFAULT, "
        "ALTER COLUMN status TYPE status USING "
        "CASE status::text "
        "  WHEN 'todo' THEN 'open' "
        "  WHEN 'cancelled' THEN 'closed' "
        "  ELSE status::text "
        "END::status, "
        "ALTER COLUMN status SET DEFAULT 'open'::status"
    )
    op.execute("DROP TYPE status_new")
