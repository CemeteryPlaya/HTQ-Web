"""Org units: add unit_type to departments + reporting relations + org settings

Revision ID: 003
Revises: 002
Create Date: 2026-04-21

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

UNIT_TYPES = ('headquarters', 'division', 'department', 'unit')
RELATION_TYPES = ('direct', 'functional', 'project')
DELETION_STRATEGIES = ('block', 'reassign_to_parent', 'cascade')


def upgrade() -> None:
    # ── unit_type on hr_departments ──────────────────────────────────────
    op.add_column(
        "hr_departments",
        sa.Column(
            "unit_type",
            sa.String(20),
            nullable=False,
            server_default="department",
        ),
    )
    op.create_check_constraint(
        "ck_department_unit_type",
        "hr_departments",
        "unit_type IN ('headquarters','division','department','unit')",
    )
    op.create_index("ix_hr_departments_unit_type", "hr_departments", ["unit_type"])

    # ── Reporting relations (subordination matrix) ───────────────────────
    op.create_table(
        "hr_reporting_relations",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "superior_position_id",
            sa.Integer,
            sa.ForeignKey("hr_positions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "subordinate_position_id",
            sa.Integer,
            sa.ForeignKey("hr_positions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "relation_type",
            sa.String(20),
            nullable=False,
            server_default="direct",
        ),
        sa.Column("effective_from", sa.Date, nullable=False, server_default=sa.func.current_date()),
        sa.Column("effective_to", sa.Date, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint(
            "superior_position_id", "subordinate_position_id", "relation_type",
            name="uq_reporting_relation",
        ),
        sa.CheckConstraint(
            "superior_position_id != subordinate_position_id",
            name="ck_no_self_relation",
        ),
        sa.CheckConstraint(
            "relation_type IN ('direct','functional','project')",
            name="ck_relation_type",
        ),
    )
    op.create_index(
        "ix_reporting_superior", "hr_reporting_relations", ["superior_position_id"]
    )
    op.create_index(
        "ix_reporting_subordinate", "hr_reporting_relations", ["subordinate_position_id"]
    )

    # ── Org settings (key-value config for org behaviour) ────────────────
    op.create_table(
        "hr_org_settings",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("key", sa.String(100), unique=True, nullable=False),
        sa.Column("value", sa.String(500), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.execute("""
        INSERT INTO hr_org_settings (key, value, description) VALUES
        ('deletion_strategy', 'block',
         'Behaviour when deleting an org unit with children: block | reassign_to_parent | cascade')
    """)


def downgrade() -> None:
    op.drop_table("hr_org_settings")
    op.drop_index("ix_reporting_subordinate", table_name="hr_reporting_relations")
    op.drop_index("ix_reporting_superior", table_name="hr_reporting_relations")
    op.drop_table("hr_reporting_relations")
    op.drop_index("ix_hr_departments_unit_type", table_name="hr_departments")
    op.drop_constraint("ck_department_unit_type", "hr_departments", type_="check")
    op.drop_column("hr_departments", "unit_type")
