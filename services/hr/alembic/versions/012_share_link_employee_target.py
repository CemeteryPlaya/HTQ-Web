"""Allow share-links to target a single employee, not just the whole org.

Adds two columns to ``hr_shareable_links``:
- ``target_type`` ('org' | 'employee') — defaults to 'org' for legacy rows.
- ``target_employee_id`` — nullable; required when ``target_type='employee'``.

Revision ID: 012
Revises: 011
Create Date: 2026-05-12
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "012"
down_revision: Union[str, None] = "011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "hr_shareable_links",
        sa.Column(
            "target_type",
            sa.String(length=16),
            nullable=False,
            server_default="org",
        ),
    )
    op.add_column(
        "hr_shareable_links",
        sa.Column("target_employee_id", sa.Integer, nullable=True),
    )
    op.create_check_constraint(
        "ck_share_link_target_type",
        "hr_shareable_links",
        "target_type IN ('org','employee')",
    )
    op.create_check_constraint(
        "ck_share_link_target_consistency",
        "hr_shareable_links",
        "(target_type = 'org' AND target_employee_id IS NULL) "
        "OR (target_type = 'employee' AND target_employee_id IS NOT NULL)",
    )
    op.create_index(
        "ix_shareable_links_target_employee",
        "hr_shareable_links",
        ["target_employee_id"],
    )
    op.alter_column("hr_shareable_links", "target_type", server_default=None)


def downgrade() -> None:
    op.drop_index("ix_shareable_links_target_employee", table_name="hr_shareable_links")
    op.drop_constraint(
        "ck_share_link_target_consistency",
        "hr_shareable_links",
        type_="check",
    )
    op.drop_constraint(
        "ck_share_link_target_type",
        "hr_shareable_links",
        type_="check",
    )
    op.drop_column("hr_shareable_links", "target_employee_id")
    op.drop_column("hr_shareable_links", "target_type")
