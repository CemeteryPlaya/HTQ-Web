"""Add HR department file folders.

Revision ID: 022_dept_file_folders
Revises: 021_merge_staffing_keys
Create Date: 2026-05-07
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "022_dept_file_folders"
down_revision: Union[str, None] = "021_merge_staffing_keys"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "hr_department_file_folders",
        sa.Column("department_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_by_name", sa.String(length=255), nullable=True),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["department_id"], ["hr_departments.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "department_id",
            "name",
            name="uq_hr_department_file_folders_department_name",
        ),
    )
    op.create_index(
        op.f("ix_hr_department_file_folders_created_by_user_id"),
        "hr_department_file_folders",
        ["created_by_user_id"],
    )
    op.create_index(
        op.f("ix_hr_department_file_folders_department_id"),
        "hr_department_file_folders",
        ["department_id"],
    )
    op.add_column("hr_department_files", sa.Column("file_folder_id", sa.Integer(), nullable=True))
    op.create_index(
        op.f("ix_hr_department_files_file_folder_id"),
        "hr_department_files",
        ["file_folder_id"],
    )
    op.create_foreign_key(
        "fk_hr_department_files_file_folder_id",
        "hr_department_files",
        "hr_department_file_folders",
        ["file_folder_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_hr_department_files_file_folder_id",
        "hr_department_files",
        type_="foreignkey",
    )
    op.drop_index(op.f("ix_hr_department_files_file_folder_id"), table_name="hr_department_files")
    op.drop_column("hr_department_files", "file_folder_id")
    op.drop_index(
        op.f("ix_hr_department_file_folders_department_id"),
        table_name="hr_department_file_folders",
    )
    op.drop_index(
        op.f("ix_hr_department_file_folders_created_by_user_id"),
        table_name="hr_department_file_folders",
    )
    op.drop_table("hr_department_file_folders")
