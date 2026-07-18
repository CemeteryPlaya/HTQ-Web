"""Staffing-table line CRUD + occupancy/payroll rollups."""

from __future__ import annotations

from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.department import Department
from app.models.employee import Employee
from app.models.position import Position
from app.models.staffing import StaffingPosition

_Q = Decimal("0.01")


def _money(v) -> str:
    return str(Decimal(str(v or 0)).quantize(_Q))


def line_out(line: StaffingPosition) -> dict:
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


class StaffingService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_lines(self, department_id: int | None = None) -> list[StaffingPosition]:
        stmt = select(StaffingPosition)
        if department_id is not None:
            stmt = stmt.where(StaffingPosition.department_id == department_id)
        return list((await self.session.execute(stmt.order_by(StaffingPosition.id))).scalars().all())

    async def _assert_fk(self, position_id: int, department_id: int) -> None:
        if await self.session.get(Position, position_id) is None:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Position not found")
        if await self.session.get(Department, department_id) is None:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Department not found")

    async def create_line(self, data: dict) -> StaffingPosition:
        await self._assert_fk(data["position_id"], data["department_id"])
        line = StaffingPosition(
            position_id=data["position_id"],
            department_id=data["department_id"],
            grade=data.get("grade"),
            headcount=Decimal(str(data.get("headcount", "1"))),
            salary=Decimal(str(data.get("salary", "0"))),
            note=data.get("note"),
        )
        self.session.add(line)
        await self.session.commit()
        await self.session.refresh(line)
        return line

    async def update_line(self, line_id: int, data: dict) -> StaffingPosition:
        line = await self.session.get(StaffingPosition, line_id)
        if line is None:
            raise HTTPException(status_code=404, detail="Staffing line not found")
        if "position_id" in data or "department_id" in data:
            await self._assert_fk(data.get("position_id", line.position_id), data.get("department_id", line.department_id))
        for f in ("position_id", "department_id", "grade", "note"):
            if f in data:
                setattr(line, f, data[f])
        if "headcount" in data:
            line.headcount = Decimal(str(data["headcount"]))
        if "salary" in data:
            line.salary = Decimal(str(data["salary"]))
        await self.session.commit()
        await self.session.refresh(line)
        return line

    async def delete_line(self, line_id: int) -> None:
        line = await self.session.get(StaffingPosition, line_id)
        if line is None:
            raise HTTPException(status_code=404, detail="Staffing line not found")
        await self.session.delete(line)
        await self.session.commit()

    async def _names(self) -> tuple[dict, dict]:
        positions = {p.id: p.title for p in (await self.session.execute(select(Position))).scalars().all()}
        departments = {d.id: d.name for d in (await self.session.execute(select(Department))).scalars().all()}
        return positions, departments

    async def occupancy(self) -> list[dict]:
        budget_rows = (await self.session.execute(
            select(StaffingPosition.position_id, StaffingPosition.department_id, func.sum(StaffingPosition.headcount))
            .group_by(StaffingPosition.position_id, StaffingPosition.department_id)
        )).all()
        filled_rows = (await self.session.execute(
            select(Employee.position_id, Employee.department_id, func.count())
            .where(Employee.status == "active", Employee.is_deleted == False)  # noqa: E712
            .group_by(Employee.position_id, Employee.department_id)
        )).all()
        filled = {(pid, did): int(cnt) for pid, did, cnt in filled_rows}
        positions, departments = await self._names()
        out: list[dict] = []
        for pid, did, budget in budget_rows:
            b = Decimal(str(budget or 0))
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

    async def payroll_summary(self) -> dict:
        lines = list((await self.session.execute(select(StaffingPosition))).scalars().all())
        _, departments = await self._names()
        by_dept: dict[int, Decimal] = {}
        total_fot = Decimal(0)
        total_budget = Decimal(0)
        for line in lines:
            fot = (line.headcount or Decimal(0)) * (line.salary or Decimal(0))
            by_dept[line.department_id] = by_dept.get(line.department_id, Decimal(0)) + fot
            total_fot += fot
            total_budget += (line.headcount or Decimal(0))
        # filled/vacant aggregate ONLY over (position, department) pairs that
        # appear in the staffing table — and clamp vacancy per group — so the
        # totals match occupancy() (a company-wide employee count would wrongly
        # offset budget from unrelated positions).
        occ = await self.occupancy()
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
