"""PMO allocation and membership history.

Revision ID: 009
Revises: 008
Create Date: 2026-05-04
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "009"
down_revision: Union[str, None] = "008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "hr_pmo_members",
        sa.Column(
            "allocation_percent",
            sa.SmallInteger(),
            nullable=False,
            server_default="100",
        ),
    )
    op.add_column(
        "hr_pmo_members",
        sa.Column(
            "is_primary",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.create_check_constraint(
        "ck_pmo_member_allocation_pct",
        "hr_pmo_members",
        "allocation_percent BETWEEN 0 AND 100",
    )
    op.create_check_constraint(
        "ck_pmo_member_dates",
        "hr_pmo_members",
        "to_date IS NULL OR to_date >= from_date",
    )

    op.drop_constraint("uq_pmo_member", "hr_pmo_members", type_="unique")
    op.create_index(
        "ux_hr_pmo_members_open_employee",
        "hr_pmo_members",
        ["pmo_id", "employee_id"],
        unique=True,
        postgresql_where=sa.text("to_date IS NULL"),
    )
    op.create_index(
        "ux_hr_pmo_members_open_primary",
        "hr_pmo_members",
        ["pmo_id"],
        unique=True,
        postgresql_where=sa.text("is_primary AND to_date IS NULL"),
    )
    op.create_index(
        "ix_pmo_members_employee_dates",
        "hr_pmo_members",
        ["employee_id", "to_date"],
    )


def downgrade() -> None:
    op.drop_index("ix_pmo_members_employee_dates", table_name="hr_pmo_members")
    op.drop_index("ux_hr_pmo_members_open_primary", table_name="hr_pmo_members")
    op.drop_index("ux_hr_pmo_members_open_employee", table_name="hr_pmo_members")
    op.create_unique_constraint("uq_pmo_member", "hr_pmo_members", ["pmo_id", "employee_id"])

    op.drop_constraint("ck_pmo_member_dates", "hr_pmo_members", type_="check")
    op.drop_constraint("ck_pmo_member_allocation_pct", "hr_pmo_members", type_="check")
    op.drop_column("hr_pmo_members", "is_primary")
    op.drop_column("hr_pmo_members", "allocation_percent")
