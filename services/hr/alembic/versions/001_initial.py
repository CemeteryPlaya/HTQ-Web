"""Initial HR schema

Revision ID: 001
Revises:
Create Date: 2026-04-10

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Enable ltree extension
    op.execute("CREATE EXTENSION IF NOT EXISTS ltree")

    # ── Departments ──────────────────────────────────────────────────────
    op.create_table(
        "hr_departments",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(255), unique=True, nullable=False),
        sa.Column("path", sa.String(500), unique=True, nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("manager_id", sa.Integer, nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_hr_departments_path", "hr_departments", ["path"])

    # ── Positions ────────────────────────────────────────────────────────
    op.create_table(
        "hr_positions",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("title", sa.String(255), unique=True, nullable=False),
        sa.Column("department_id", sa.Integer, sa.ForeignKey("hr_departments.id"), nullable=False),
        sa.Column("grade", sa.Integer, nullable=False, server_default="1"),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("requirements", sa.JSON, nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # ── Employees ────────────────────────────────────────────────────────
    op.create_table(
        "hr_employees",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer, unique=True, nullable=True),
        sa.Column("first_name", sa.String(100), nullable=False),
        sa.Column("last_name", sa.String(100), nullable=False),
        sa.Column("middle_name", sa.String(100), nullable=True),
        sa.Column("email", sa.String(255), unique=True, nullable=False),
        sa.Column("phone", sa.String(20), nullable=True),
        sa.Column("department_id", sa.Integer, sa.ForeignKey("hr_departments.id"), nullable=False),
        sa.Column("position_id", sa.Integer, sa.ForeignKey("hr_positions.id"), nullable=False),
        sa.Column("hire_date", sa.Date, nullable=False),
        sa.Column("termination_date", sa.Date, nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("avatar_url", sa.String(500), nullable=True),
        sa.Column("bio", sa.Text, nullable=True),
        sa.Column("is_deleted", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_hr_employees_email", "hr_employees", ["email"])
    op.create_index("ix_hr_employees_status", "hr_employees", ["status"])

    # Add manager FK to departments now that employees table exists
    op.create_foreign_key(
        "fk_hr_departments_manager",
        "hr_departments", "hr_employees",
        ["manager_id"], ["id"],
        use_alter=True,
    )

    # ── Vacancies ────────────────────────────────────────────────────────
    op.create_table(
        "hr_vacancies",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("department_id", sa.Integer, sa.ForeignKey("hr_departments.id"), nullable=False),
        sa.Column("position_id", sa.Integer, sa.ForeignKey("hr_positions.id"), nullable=False),
        sa.Column("description", sa.Text, nullable=False, server_default=""),
        sa.Column("requirements", sa.Text, nullable=False, server_default=""),
        sa.Column("status", sa.String(20), nullable=False, server_default="open"),
        sa.Column("opened_at", sa.Date, server_default=sa.func.current_date()),
        sa.Column("closed_at", sa.Date, nullable=True),
        sa.Column("assigned_recruiter_id", sa.Integer, sa.ForeignKey("hr_employees.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_hr_vacancies_status", "hr_vacancies", ["status"])

    # ── Applications ─────────────────────────────────────────────────────
    op.create_table(
        "hr_applications",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("vacancy_id", sa.Integer, sa.ForeignKey("hr_vacancies.id"), nullable=False),
        sa.Column("candidate_name", sa.String(255), nullable=False),
        sa.Column("candidate_email", sa.String(255), nullable=False),
        sa.Column("candidate_phone", sa.String(20), nullable=True),
        sa.Column("resume_url", sa.String(500), nullable=True),
        sa.Column("cover_letter", sa.Text, nullable=True),
        sa.Column("status", sa.String(30), nullable=False, server_default="new"),
        sa.Column("applied_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # ── Time Entries ─────────────────────────────────────────────────────
    op.create_table(
        "hr_time_entries",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("employee_id", sa.Integer, sa.ForeignKey("hr_employees.id"), nullable=False),
        sa.Column("date", sa.Date, nullable=False),
        sa.Column("start_time", sa.Time, nullable=False),
        sa.Column("end_time", sa.Time, nullable=False),
        sa.Column("break_minutes", sa.Integer, nullable=False, server_default="0"),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("project", sa.String(255), nullable=True),
        sa.Column("task", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("employee_id", "date", "start_time", name="uq_employee_time_entry"),
    )

    # ── Documents ────────────────────────────────────────────────────────
    op.create_table(
        "hr_documents",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("employee_id", sa.Integer, sa.ForeignKey("hr_employees.id"), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("doc_type", sa.String(50), nullable=False),
        sa.Column("file_path", sa.String(500), nullable=False),
        sa.Column("file_size", sa.Integer, nullable=False),
        sa.Column("mime_type", sa.String(100), nullable=False, server_default="application/octet-stream"),
        sa.Column("uploaded_by", sa.Integer, sa.ForeignKey("hr_employees.id"), nullable=False),
        sa.Column("metadata", sa.JSON, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # ── Audit Log ────────────────────────────────────────────────────────
    op.create_table(
        "hr_audit_log",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("entity_type", sa.String(50), nullable=False),
        sa.Column("entity_id", sa.Integer, nullable=False),
        sa.Column("action", sa.String(20), nullable=False),
        sa.Column("old_values", sa.JSON, nullable=True),
        sa.Column("new_values", sa.JSON, nullable=True),
        sa.Column("changed_by", sa.Integer, sa.ForeignKey("hr_employees.id"), nullable=False),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("user_agent", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_audit_log_entity", "hr_audit_log", ["entity_type", "entity_id"])


def downgrade() -> None:
    op.drop_table("hr_audit_log")
    op.drop_table("hr_documents")
    op.drop_table("hr_time_entries")
    op.drop_table("hr_applications")
    op.drop_table("hr_vacancies")
    op.drop_constraint("fk_hr_departments_manager", "hr_departments", type_="foreignkey")
    op.drop_table("hr_employees")
    op.drop_table("hr_positions")
    op.drop_table("hr_departments")
