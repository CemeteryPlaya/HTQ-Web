"""Position weight & level system + level thresholds config table

Revision ID: 002
Revises: 001
Create Date: 2026-04-21

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Level thresholds config ──────────────────────────────────────────
    op.create_table(
        "hr_level_thresholds",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("level_number", sa.Integer, nullable=False, unique=True),
        sa.Column("weight_from", sa.Integer, nullable=False),
        sa.Column("weight_to", sa.Integer, nullable=False),
        sa.Column("label", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint("weight_from <= weight_to", name="ck_threshold_range"),
        sa.CheckConstraint("level_number >= 1", name="ck_threshold_level_positive"),
    )
    op.create_index("ix_hr_level_thresholds_level", "hr_level_thresholds", ["level_number"], unique=True)

    # Seed default thresholds (5 levels covering weight 0–499+)
    op.execute("""
        INSERT INTO hr_level_thresholds (level_number, weight_from, weight_to, label) VALUES
        (1, 0,   99,  'Топ-менеджмент'),
        (2, 100, 199, 'Руководство'),
        (3, 200, 299, 'Менеджмент'),
        (4, 300, 399, 'Специалисты'),
        (5, 400, 499, 'Сотрудники')
    """)

    # ── Add weight and level to positions ───────────────────────────────
    # weight: global ordering value (lower = higher in hierarchy)
    op.add_column("hr_positions", sa.Column(
        "weight", sa.Integer, nullable=False, server_default="100"
    ))
    # level: cached value computed from weight via hr_level_thresholds
    op.add_column("hr_positions", sa.Column(
        "level", sa.Integer, nullable=False, server_default="2"
    ))

    op.create_index("ix_hr_positions_weight", "hr_positions", ["weight"])
    op.create_index("ix_hr_positions_level", "hr_positions", ["level"])

    # Unique constraint on weight globally across all positions
    op.create_unique_constraint("uq_positions_weight_global", "hr_positions", ["weight"])


def downgrade() -> None:
    op.drop_constraint("uq_positions_weight_global", "hr_positions", type_="unique")
    op.drop_index("ix_hr_positions_level", table_name="hr_positions")
    op.drop_index("ix_hr_positions_weight", table_name="hr_positions")
    op.drop_column("hr_positions", "level")
    op.drop_column("hr_positions", "weight")
    op.drop_index("ix_hr_level_thresholds_level", table_name="hr_level_thresholds")
    op.drop_table("hr_level_thresholds")
