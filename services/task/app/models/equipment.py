"""Equipment model — physical resources (machinery/vehicles) the task service owns.

Unlike task_users / task_departments (replicas synced from other services),
equipment is a first-class entity owned by the task domain: there is no separate
equipment service. Used for resource-planning Gantt (grouping tasks by machine).
"""

from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import BaseModel


class Equipment(BaseModel):
    __tablename__ = "task_equipment"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    inventory_no: Mapped[str | None] = mapped_column(String(50), nullable=True)
    category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true", index=True
    )
