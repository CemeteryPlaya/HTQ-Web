"""Multi-department tasks: task_department_links junction.

A task may now span several departments (e.g. a cross-functional
initiative). The single ``tasks.department_id`` column is kept as the
"primary" department (first selected, used for scoping/back-compat);
the full set lives in ``task_department_links``.

Existing tasks with a non-NULL ``department_id`` are back-filled into the
junction so the M:M is consistent from day one.

Revision ID: 014
Revises: 013
Create Date: 2026-05-22
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "014"
down_revision: Union[str, None] = "013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Idempotent DDL — under PgBouncer transaction-pooling a partial run can
    # commit the table/index before a later step fails, so re-runs must not
    # choke on "already exists".
    op.execute(
        "CREATE TABLE IF NOT EXISTS task_department_links ("
        " task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,"
        " department_id INTEGER NOT NULL REFERENCES task_departments(id) ON DELETE CASCADE,"
        " PRIMARY KEY (task_id, department_id)"
        ")"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_task_department_links_department_id "
        "ON task_department_links (department_id)"
    )
    # Back-fill from the existing primary department — but ONLY for
    # departments that actually exist in the local replica. The replica
    # (task_departments, fed by Redis pub/sub from hr-service) may lag, so
    # tasks pointing at a not-yet-synced department are skipped rather than
    # violating the FK. They'll get linked once a user re-saves the task.
    op.execute(
        "INSERT INTO task_department_links (task_id, department_id) "
        "SELECT t.id, t.department_id FROM tasks t "
        "WHERE t.department_id IS NOT NULL "
        "AND EXISTS (SELECT 1 FROM task_departments d WHERE d.id = t.department_id) "
        "ON CONFLICT DO NOTHING"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_task_department_links_department_id")
    op.execute("DROP TABLE IF EXISTS task_department_links")
