"""Create hr_employee_card (Т-2 scalars).

Revision ID: 015_create_employee_card
Revises: 014_backfill_position_perms
Create Date: 2026-05-29
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "015_create_employee_card"
down_revision = "014_backfill_position_perms"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "hr_employee_card",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("hr_employees.id", ondelete="CASCADE"), nullable=False),
        sa.Column("salary", sa.Numeric(12, 2), nullable=True),
        sa.Column("bonus", sa.Numeric(12, 2), nullable=True),
        sa.Column("bank_account", sa.String(64), nullable=True),
        sa.Column("passport_data", sa.Text(), nullable=True),
        sa.Column("inn", sa.String(20), nullable=True),
        sa.Column("birth_date", sa.Date(), nullable=True),
        sa.Column("birth_place", sa.String(255), nullable=True),
        sa.Column("citizenship", sa.String(100), nullable=True),
        sa.Column("sro_permit_number", sa.String(100), nullable=True),
        sa.Column("sro_permit_expiry", sa.Date(), nullable=True),
        sa.Column("safety_cert_number", sa.String(100), nullable=True),
        sa.Column("safety_cert_expiry", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_unique_constraint("uq_hr_employee_card_employee", "hr_employee_card", ["employee_id"])
    op.create_index("ix_hr_employee_card_employee_id", "hr_employee_card", ["employee_id"])


def downgrade() -> None:
    op.drop_index("ix_hr_employee_card_employee_id", table_name="hr_employee_card")
    op.drop_constraint("uq_hr_employee_card_employee", "hr_employee_card", type_="unique")
    op.drop_table("hr_employee_card")
