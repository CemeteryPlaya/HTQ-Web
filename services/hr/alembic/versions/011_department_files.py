"""Add HR department file metadata.

Revision ID: 011
Revises: 010
Create Date: 2026-05-06
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "011"
down_revision: Union[str, None] = "010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "hr_department_files",
        sa.Column("department_id", sa.Integer(), nullable=False),
        sa.Column("media_file_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=512), nullable=False),
        sa.Column("file_url", sa.String(length=1024), nullable=False),
        sa.Column("file_size", sa.BigInteger(), nullable=False),
        sa.Column("mime_type", sa.String(length=255), nullable=False),
        sa.Column("uploaded_by_user_id", sa.Integer(), nullable=True),
        sa.Column("uploaded_by_name", sa.String(length=255), nullable=True),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["department_id"], ["hr_departments.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_hr_department_files_department_id"),
        "hr_department_files",
        ["department_id"],
    )
    op.create_index(
        op.f("ix_hr_department_files_media_file_id"),
        "hr_department_files",
        ["media_file_id"],
    )
    op.create_index(
        op.f("ix_hr_department_files_uploaded_by_user_id"),
        "hr_department_files",
        ["uploaded_by_user_id"],
    )
    op.alter_column("hr_department_files", "description", server_default=None)


def downgrade() -> None:
    op.drop_index(op.f("ix_hr_department_files_uploaded_by_user_id"), table_name="hr_department_files")
    op.drop_index(op.f("ix_hr_department_files_media_file_id"), table_name="hr_department_files")
    op.drop_index(op.f("ix_hr_department_files_department_id"), table_name="hr_department_files")
    op.drop_table("hr_department_files")
