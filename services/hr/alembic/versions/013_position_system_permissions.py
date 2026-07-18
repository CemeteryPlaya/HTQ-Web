"""Position: is_system flag + custom permissions matrix.

Existing positions become "system" (protected from rename/delete) so the
project's baseline hierarchy (CEO, Board, Directors, Specialists) stays
intact. Newly created positions default to ``is_system=False`` and can
carry an explicit ``permissions`` JSONB matrix that overrides the legacy
title-based HR-level heuristic.

Revision ID: 013
Revises: 012
Create Date: 2026-05-21
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "013"
down_revision: Union[str, None] = "012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "hr_positions",
        sa.Column(
            "is_system",
            sa.Boolean,
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "hr_positions",
        sa.Column("permissions", sa.JSON, nullable=True),
    )

    # Everything that exists at migration time is treated as the system
    # baseline. Drop the server_default so newly inserted rows fall back
    # to the model-level default (False).
    op.execute("UPDATE hr_positions SET is_system = TRUE")
    op.alter_column("hr_positions", "is_system", server_default=None)

    op.create_index(
        "ix_hr_positions_is_system",
        "hr_positions",
        ["is_system"],
    )


def downgrade() -> None:
    op.drop_index("ix_hr_positions_is_system", table_name="hr_positions")
    op.drop_column("hr_positions", "permissions")
    op.drop_column("hr_positions", "is_system")
