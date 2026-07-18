"""Add employee department scope to task service.

Revision ID: 003_employee_department_scope
Revises: 002_replica_tables
Create Date: 2026-05-05
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "003_employee_department_scope"
down_revision: Union[str, None] = "002_replica_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "task_users",
        sa.Column("email", sa.String(length=254), nullable=False, server_default=""),
    )
    op.add_column(
        "task_users",
        sa.Column("department_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_task_users_department_id",
        "task_users",
        "task_departments",
        ["department_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_task_users_department_id", "task_users", ["department_id"])

    op.add_column(
        "project_versions",
        sa.Column("department_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_project_versions_department_id",
        "project_versions",
        "task_departments",
        ["department_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_project_versions_department_id", "project_versions", ["department_id"])


def downgrade() -> None:
    op.drop_index("ix_project_versions_department_id", table_name="project_versions")
    op.drop_constraint("fk_project_versions_department_id", "project_versions", type_="foreignkey")
    op.drop_column("project_versions", "department_id")

    op.drop_index("ix_task_users_department_id", table_name="task_users")
    op.drop_constraint("fk_task_users_department_id", "task_users", type_="foreignkey")
    op.drop_column("task_users", "department_id")
    op.drop_column("task_users", "email")
