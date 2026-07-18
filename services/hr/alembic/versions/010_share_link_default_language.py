"""Add default language to shareable org links.

Revision ID: 010
Revises: 009
Create Date: 2026-05-04
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "010"
down_revision: Union[str, None] = "009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "hr_shareable_links",
        sa.Column(
            "default_language",
            sa.String(length=2),
            nullable=False,
            server_default="ru",
        ),
    )
    op.create_check_constraint(
        "ck_share_link_default_language",
        "hr_shareable_links",
        "default_language IN ('ru','en')",
    )
    op.alter_column("hr_shareable_links", "default_language", server_default=None)


def downgrade() -> None:
    op.drop_constraint(
        "ck_share_link_default_language",
        "hr_shareable_links",
        type_="check",
    )
    op.drop_column("hr_shareable_links", "default_language")
