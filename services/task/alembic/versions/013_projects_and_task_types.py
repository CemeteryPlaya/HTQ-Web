"""Replace ProjectVersion with Project + DB-backed TaskType registry.

Three independent migrations bundled together because they share the
"tasks classification" theme:

1. Drop the ``project_versions`` table, ``versionstatus`` enum and the
   ``tasks.version_id`` FK. They're replaced by a richer ``projects``
   table linked through ``tasks.project_id``. NULL ``project_id``
   means a "standalone" task — a first-class state in the UI.

2. Replace the hard-coded ``tasktype`` PG ENUM column on ``tasks`` with
   a ``tasks.task_type_id`` FK pointing at a new ``task_types`` table.
   The five legacy values are seeded as ``is_system=true`` rows so old
   data and UI continue working; users can now add custom types
   (e.g. ``maintenance``, ``onboarding``) for non-IT workflows.

Both are forward-only refactors; the downgrade restores the legacy
schema for development rollbacks.

Revision ID: 013
Revises: 012
Create Date: 2026-05-22
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "013"
down_revision: Union[str, None] = "012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ----- 1. task_types DDL ------------------------------------------------- #


SEED_TYPES = [
    ("task", "Задача", "#3b82f6", "check-square"),
    ("bug", "Баг", "#ef4444", "bug"),
    ("story", "История", "#22c55e", "book-open"),
    ("epic", "Эпик", "#8b5cf6", "layers"),
    ("subtask", "Подзадача", "#6b7280", "list-todo"),
]


def upgrade() -> None:
    # 1a. Create task_types table -----------------------------------------
    op.create_table(
        "task_types",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("slug", sa.String(50), unique=True, nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("color", sa.String(20), nullable=False, server_default="#6b7280"),
        sa.Column("icon", sa.String(50), nullable=True),
        sa.Column("is_system", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
    )
    op.create_index("ix_task_types_slug", "task_types", ["slug"], unique=True)

    # Seed five system rows.
    for slug, name, color, icon in SEED_TYPES:
        op.execute(
            sa.text(
                "INSERT INTO task_types (slug, name, color, icon, is_system) "
                "VALUES (:slug, :name, :color, :icon, true)"
            ).bindparams(slug=slug, name=name, color=color, icon=icon)
        )

    # 1b. Add tasks.task_type_id, back-fill from enum, drop enum ----------
    op.execute(
        "ALTER TABLE tasks ADD COLUMN task_type_id INTEGER "
        "REFERENCES task_types(id) ON DELETE SET NULL"
    )
    op.execute("CREATE INDEX ix_tasks_task_type_id ON tasks(task_type_id)")
    op.execute(
        "UPDATE tasks SET task_type_id = tt.id "
        "FROM task_types tt WHERE tt.slug = tasks.task_type::text"
    )
    op.execute("ALTER TABLE tasks DROP COLUMN task_type")
    op.execute("DROP TYPE IF EXISTS tasktype")

    # ----- 2. projects DDL + version teardown ---------------------------

    # Idempotent enum creation (create_type=False so create_table won't
    # double-create it; checkfirst so re-runs after a partial failure work).
    project_status_enum = postgresql.ENUM(
        "active", "completed", "archived", name="project_status", create_type=False
    )
    project_status_enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "projects",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(200), unique=True, nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "status",
            project_status_enum,
            nullable=False,
            server_default="active",
        ),
        sa.Column("color", sa.String(20), nullable=False, server_default="#3b82f6"),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column(
            "owner_id",
            sa.Integer(),
            sa.ForeignKey("task_users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "department_id",
            sa.Integer(),
            sa.ForeignKey("task_departments.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
    )
    op.create_index("ix_projects_owner_id", "projects", ["owner_id"])
    op.create_index("ix_projects_department_id", "projects", ["department_id"])
    op.create_index("ix_projects_status", "projects", ["status"])

    # Add tasks.project_id BEFORE dropping version_id. This is so we can
    # migrate any meaningful linkage; in practice though there is no
    # automatic mapping (releases ≠ projects), so we just leave existing
    # tasks unlinked.
    op.execute(
        "ALTER TABLE tasks ADD COLUMN project_id INTEGER "
        "REFERENCES projects(id) ON DELETE SET NULL"
    )
    op.execute("CREATE INDEX ix_tasks_project_id ON tasks(project_id)")

    # Drop the version FK / table / enum.
    op.execute("ALTER TABLE tasks DROP COLUMN IF EXISTS version_id")
    op.execute("DROP TABLE IF EXISTS project_versions")
    op.execute("DROP TYPE IF EXISTS versionstatus")


def downgrade() -> None:
    # Restore project_versions skeleton ----------------------------------
    op.execute(
        "DO $$ BEGIN CREATE TYPE versionstatus AS ENUM "
        "('planned', 'in_progress', 'released', 'archived'); "
        "EXCEPTION WHEN duplicate_object THEN null; END $$;"
    )
    op.create_table(
        "project_versions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(200), unique=True, nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "status",
            sa.Enum("planned", "in_progress", "released", "archived",
                    name="versionstatus", create_type=False),
            nullable=False,
            server_default="planned",
        ),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("release_date", sa.Date(), nullable=True),
        sa.Column(
            "department_id",
            sa.Integer(),
            sa.ForeignKey("task_departments.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now()
        ),
    )
    op.execute(
        "ALTER TABLE tasks ADD COLUMN version_id INTEGER "
        "REFERENCES project_versions(id) ON DELETE SET NULL"
    )

    op.execute("DROP INDEX IF EXISTS ix_tasks_project_id")
    op.execute("ALTER TABLE tasks DROP COLUMN IF EXISTS project_id")

    op.execute("DROP INDEX IF EXISTS ix_projects_status")
    op.execute("DROP INDEX IF EXISTS ix_projects_department_id")
    op.execute("DROP INDEX IF EXISTS ix_projects_owner_id")
    op.drop_table("projects")
    op.execute("DROP TYPE IF EXISTS project_status")

    # Restore task_type enum ---------------------------------------------
    op.execute(
        "DO $$ BEGIN CREATE TYPE tasktype AS ENUM "
        "('task', 'bug', 'story', 'epic', 'subtask'); "
        "EXCEPTION WHEN duplicate_object THEN null; END $$;"
    )
    op.execute(
        "ALTER TABLE tasks ADD COLUMN task_type tasktype "
        "NOT NULL DEFAULT 'task'::tasktype"
    )
    op.execute(
        "UPDATE tasks SET task_type = tt.slug::tasktype "
        "FROM task_types tt WHERE tt.id = tasks.task_type_id "
        "AND tt.slug IN ('task','bug','story','epic','subtask')"
    )
    op.execute("DROP INDEX IF EXISTS ix_tasks_task_type_id")
    op.execute("ALTER TABLE tasks DROP COLUMN IF EXISTS task_type_id")
    op.execute("DROP INDEX IF EXISTS ix_task_types_slug")
    op.drop_table("task_types")
