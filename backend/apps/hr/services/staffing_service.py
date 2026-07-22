"""Штатное расписание (staffing table) — порт
services/hr/app/services/staffing_service.py.

Р2: dramatiq-события не портируются (исходник их не шлёт).
"""
from __future__ import annotations

from decimal import Decimal

from django.db.models import Count, Sum

from apps.hr.models import Department, Employee, EmployeeStatus, Position, StaffingPosition

_Q = Decimal("0.01")


def _money(v) -> str:
    return str(Decimal(str(v if v is not None else 0)).quantize(_Q))


class StaffingLineNotFound(Exception):
    """404 "Staffing line not found" — порт StaffingService.update_line/delete_line."""


class StaffingRefNotFound(Exception):
    """422 — position_id/department_id не существует (порт _assert_fk)."""

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(detail)


def line_out(line: StaffingPosition) -> dict:
    """StaffingLineOut — headcount/salary/fot СТРОКАМИ, квантованными до 2 зн."""
    fot = (line.headcount or Decimal(0)) * (line.salary or Decimal(0))
    return {
        "id": line.id,
        "position_id": line.position_id,
        "department_id": line.department_id,
        "grade": line.grade,
        "headcount": _money(line.headcount),
        "salary": _money(line.salary),
        "fot": _money(fot),
        "note": line.note,
    }


def list_lines(department_id: int | None = None) -> list[StaffingPosition]:
    qs = StaffingPosition.objects.order_by("id")
    if department_id is not None:
        qs = qs.filter(department_id=department_id)
    return list(qs)


def _assert_fk(position_id: int, department_id: int) -> None:
    if not Position.objects.filter(id=position_id).exists():
        raise StaffingRefNotFound("Position not found")
    if not Department.objects.filter(id=department_id).exists():
        raise StaffingRefNotFound("Department not found")


def create_line(data: dict) -> StaffingPosition:
    _assert_fk(data["position_id"], data["department_id"])
    return StaffingPosition.objects.create(
        position_id=data["position_id"],
        department_id=data["department_id"],
        grade=data.get("grade"),
        headcount=Decimal(str(data.get("headcount", "1"))),
        salary=Decimal(str(data.get("salary", "0"))),
        note=data.get("note"),
    )


def update_line(line_id: int, data: dict) -> StaffingPosition:
    line = StaffingPosition.objects.filter(id=line_id).first()
    if line is None:
        raise StaffingLineNotFound
    if "position_id" in data or "department_id" in data:
        _assert_fk(
            data.get("position_id", line.position_id),
            data.get("department_id", line.department_id),
        )
    for f in ("position_id", "department_id", "grade", "note"):
        if f in data:
            setattr(line, f, data[f])
    if "headcount" in data:
        line.headcount = Decimal(str(data["headcount"]))
    if "salary" in data:
        line.salary = Decimal(str(data["salary"]))
    line.save()
    return line


def delete_line(line_id: int) -> None:
    line = StaffingPosition.objects.filter(id=line_id).first()
    if line is None:
        raise StaffingLineNotFound
    line.delete()


def _names() -> tuple[dict, dict]:
    positions = {p.id: p.title for p in Position.objects.all()}
    departments = {d.id: d.name for d in Department.objects.all()}
    return positions, departments


def occupancy() -> list[dict]:
    budget_rows = (
        StaffingPosition.objects
        .values("position_id", "department_id")
        .annotate(budget=Sum("headcount"))
    )
    filled_rows = (
        Employee.objects
        .filter(status=EmployeeStatus.ACTIVE, is_deleted=False)
        .values("position_id", "department_id")
        .annotate(cnt=Count("id"))
    )
    filled = {(r["position_id"], r["department_id"]): r["cnt"] for r in filled_rows}
    positions, departments = _names()
    out: list[dict] = []
    for row in budget_rows:
        pid, did = row["position_id"], row["department_id"]
        b = Decimal(str(row["budget"] or 0))
        f = filled.get((pid, did), 0)
        vac = b - f
        if vac < 0:
            vac = Decimal(0)
        out.append({
            "position_id": pid,
            "position_title": positions.get(pid),
            "department_id": did,
            "department_name": departments.get(did),
            "budgeted": _money(b),
            "filled": f,
            "vacant": _money(vac),
        })
    return out


def payroll_summary() -> dict:
    lines = list(StaffingPosition.objects.all())
    _, departments = _names()
    by_dept: dict[int, Decimal] = {}
    total_fot = Decimal(0)
    total_budget = Decimal(0)
    for line in lines:
        fot = (line.headcount or Decimal(0)) * (line.salary or Decimal(0))
        by_dept[line.department_id] = by_dept.get(line.department_id, Decimal(0)) + fot
        total_fot += fot
        total_budget += (line.headcount or Decimal(0))
    # filled/vacant агрегируются ТОЛЬКО по (position, department) парам,
    # присутствующим в staffing-таблице, с ограничением vacancy по группе —
    # так итоги совпадают с occupancy() (общий по компании подсчёт
    # сотрудников некорректно сдвинул бы бюджет от несвязанных должностей).
    occ = occupancy()
    total_filled = sum(int(g["filled"]) for g in occ)
    total_vacant = sum(Decimal(g["vacant"]) for g in occ)
    return {
        "by_department": [
            {"department_id": did, "department_name": departments.get(did), "fot": _money(fot)}
            for did, fot in by_dept.items()
        ],
        "total_fot": _money(total_fot),
        "total_budgeted": _money(total_budget),
        "total_filled": total_filled,
        "total_vacant": _money(total_vacant),
    }
