"""Add resource planning: task_equipment + task_assignments (M2M) + backfill.

Introduces equipment as a first-class task-domain entity and a many-to-many
assignment table linking tasks to employees and/or equipment. Existing single
``tasks.assignee_id`` values are backfilled as employee assignments so the
resource-planning Gantt shows current data immediately.

Revision ID: 015_resource_assignments
Revises: 014
Create Date: 2026-06-09
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "015_resource_assignments"
down_revision: Union[str, None] = "014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "task_equipment",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("inventory_no", sa.String(length=50), nullable=True),
        sa.Column("category", sa.String(length=100), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_task_equipment_is_active", "task_equipment", ["is_active"])

    op.create_table(
        "task_assignments",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("employee_id", sa.Integer(), nullable=True),
        sa.Column("equipment_id", sa.Integer(), nullable=True),
        sa.Column("role", sa.String(length=100), nullable=True),
        sa.Column("allocation", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["employee_id"], ["task_users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["equipment_id"], ["task_equipment.id"], ondelete="CASCADE"),
        sa.CheckConstraint(
            "(employee_id IS NOT NULL)::int + (equipment_id IS NOT NULL)::int = 1",
            name="ck_assignment_exactly_one_resource",
        ),
        sa.UniqueConstraint(
            "task_id", "employee_id", "equipment_id", name="uq_task_assignment"
        ),
    )
    op.create_index("ix_task_assignments_task_id", "task_assignments", ["task_id"])
    op.create_index("ix_task_assignments_employee_id", "task_assignments", ["employee_id"])
    op.create_index("ix_task_assignments_equipment_id", "task_assignments", ["equipment_id"])

    # Backfill: every task with a legacy single assignee becomes an employee assignment.
    op.execute(
        """
        INSERT INTO task_assignments (task_id, employee_id, allocation)
        SELECT id, assignee_id, 100
        FROM tasks
        WHERE assignee_id IS NOT NULL
        ON CONFLICT DO NOTHING
        """
    )


def downgrade() -> None:
    op.drop_table("task_assignments")
    op.drop_index("ix_task_equipment_is_active", table_name="task_equipment")
    op.drop_table("task_equipment")
