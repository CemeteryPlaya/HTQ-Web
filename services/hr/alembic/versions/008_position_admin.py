"""Position admin: level colors and weight audit.

Revision ID: 008
Revises: 007
Create Date: 2026-05-04
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "008"
down_revision: Union[str, None] = "007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "hr_level_thresholds",
        sa.Column("color", sa.String(length=7), nullable=True),
    )
    op.execute(
        """
        UPDATE hr_level_thresholds
        SET color = CASE level_number
            WHEN 1 THEN '#8b5cf6'
            WHEN 2 THEN '#3b82f6'
            WHEN 3 THEN '#10b981'
            WHEN 4 THEN '#f59e0b'
            WHEN 5 THEN '#6b7280'
            ELSE '#64748b'
        END
        WHERE color IS NULL
        """
    )

    op.create_table(
        "hr_position_weight_audit",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "position_id",
            sa.Integer(),
            sa.ForeignKey("hr_positions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("old_weight", sa.Integer(), nullable=True),
        sa.Column("new_weight", sa.Integer(), nullable=True),
        sa.Column("old_level", sa.Integer(), nullable=True),
        sa.Column("new_level", sa.Integer(), nullable=True),
        sa.Column("changed_by", sa.Integer(), nullable=True),
        sa.Column(
            "changed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("reason", sa.String(length=64), nullable=True),
    )
    op.create_index(
        "ix_hr_position_weight_audit_position",
        "hr_position_weight_audit",
        ["position_id", "changed_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_hr_position_weight_audit_position",
        table_name="hr_position_weight_audit",
    )
    op.drop_table("hr_position_weight_audit")
    op.drop_column("hr_level_thresholds", "color")
