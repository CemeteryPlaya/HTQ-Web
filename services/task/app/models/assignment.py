"""TaskAssignment — many-to-many between a task and its resources.

A single task can involve several employees AND several pieces of equipment at
once. Each row links a task to exactly ONE resource — either an employee
(``task_users``) or a piece of equipment (``task_equipment``).

Design note: instead of a polymorphic ``(resource_type, resource_id)`` pair —
which cannot carry a real foreign key — we keep two nullable FKs plus a CHECK
constraint enforcing that exactly one is set. This preserves referential
integrity at the DB level while staying a single table.
"""

from sqlalchemy import CheckConstraint, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import BaseModel


class TaskAssignment(BaseModel):
    __tablename__ = "task_assignments"
    __table_args__ = (
        CheckConstraint(
            "(employee_id IS NOT NULL)::int + (equipment_id IS NOT NULL)::int = 1",
            name="ck_assignment_exactly_one_resource",
        ),
        UniqueConstraint(
            "task_id", "employee_id", "equipment_id", name="uq_task_assignment"
        ),
    )

    task_id: Mapped[int] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    employee_id: Mapped[int | None] = mapped_column(
        ForeignKey("task_users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    equipment_id: Mapped[int | None] = mapped_column(
        ForeignKey("task_equipment.id", ondelete="CASCADE"), nullable=True, index=True
    )
    # Optional context for the assignment.
    role: Mapped[str | None] = mapped_column(String(100), nullable=True)
    allocation: Mapped[int] = mapped_column(
        Integer, nullable=False, default=100, server_default="100"
    )  # % of resource capacity, reserved for future overload analysis
