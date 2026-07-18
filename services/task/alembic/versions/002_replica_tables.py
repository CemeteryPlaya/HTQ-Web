"""Add task-service replica tables: task_users + task_departments.

These mirror users (from user-service) and departments (from hr-service) so
the task domain has zero cross-schema joins. Populated by the
`run_user_replica_sync_loop` background task in app.workers.replica_sync.

Revision ID: 002_replica_tables
Revises: 001_initial
Create Date: 2026-04-25
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "002_replica_tables"
down_revision: Union[str, None] = "001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "task_users",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=False),
        sa.Column("username", sa.String(length=150), nullable=False),
        sa.Column("first_name", sa.String(length=150), nullable=False, server_default=""),
        sa.Column("last_name", sa.String(length=150), nullable=False, server_default=""),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )
    op.create_table(
        "task_departments",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=False),
        sa.Column("name", sa.String(length=150), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("task_departments")
    op.drop_table("task_users")
