"""Schemas for Gantt endpoints: task-report Gantt + resource-planning Gantt."""

from datetime import date

from pydantic import BaseModel, Field


# ─────────────────────────── Reports Gantt (flat) ───────────────────────────

class GanttTask(BaseModel):
    """One bar in the report Gantt. Flat list; hierarchy via ``parent``."""

    id: str
    key: str
    text: str
    start_date: date | None = None
    end_date: date | None = None
    progress: float = 0.0
    status: str
    parent: str | None = None
    assignees: list[str] = []


class ReportsGanttResponse(BaseModel):
    tasks: list[GanttTask]


# ───────────────────────── Resource Gantt (grouped) ─────────────────────────

class AllocatedTask(BaseModel):
    task_id: str
    key: str
    title: str
    start_date: date | None = None
    end_date: date | None = None
    progress: float = 0.0
    status: str
    allocation: int = 100


class ResourceRow(BaseModel):
    resource_id: str                 # e.g. "emp_8" / "eq_3"
    resource_kind: str               # "employee" | "equipment"
    resource_name: str
    meta: dict = Field(default_factory=dict)
    allocated_tasks: list[AllocatedTask] = []


class ResourceGanttResponse(BaseModel):
    range: dict
    resources: list[ResourceRow]


# ─────────────────────────────── Equipment ──────────────────────────────────

class EquipmentCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    inventory_no: str | None = Field(None, max_length=50)
    category: str | None = Field(None, max_length=100)


class EquipmentUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    inventory_no: str | None = Field(None, max_length=50)
    category: str | None = Field(None, max_length=100)
    is_active: bool | None = None


class EquipmentResponse(BaseModel):
    id: int
    name: str
    inventory_no: str | None = None
    category: str | None = None
    is_active: bool

    model_config = {"from_attributes": True}


# ─────────────────────────────── Assignments ────────────────────────────────

class AssignmentCreate(BaseModel):
    task_id: int
    employee_id: int | None = None
    equipment_id: int | None = None
    role: str | None = Field(None, max_length=100)
    allocation: int = Field(100, ge=0, le=100)


class AssignmentResponse(BaseModel):
    id: int
    task_id: int
    employee_id: int | None = None
    equipment_id: int | None = None
    role: str | None = None
    allocation: int

    model_config = {"from_attributes": True}
