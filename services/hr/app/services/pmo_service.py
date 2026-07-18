"""PMO service — CRUD + members + org-chart data."""

from datetime import date

import structlog
from fastapi import HTTPException, status
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.employee import Employee
from app.models.position import Position
from app.models.pmo import PMO, PMOMember
from app.repositories.base_repo import BaseRepository

logger = structlog.get_logger()


class PMOService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = BaseRepository(PMO, session)

    # ── PMO CRUD ───────────────────────────────────────────────────────

    async def list_pmos(self, *, status_filter: str | None = None) -> list[PMO]:
        filters = {"status": status_filter} if status_filter else None
        items, _ = await self.repo.list(filters=filters, limit=500, order_by="name")
        return list(items)

    async def get_pmo(self, id: int) -> PMO:
        pmo = await self.repo.get(id)
        if not pmo:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="PMO not found")
        return pmo

    async def create_pmo(self, data: dict) -> PMO:
        # Check unique code
        stmt = select(PMO).where(PMO.code == data["code"])
        existing = (await self.session.execute(stmt)).scalar_one_or_none()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"PMO with code '{data['code']}' already exists",
            )
        pmo = await self.repo.create(data)
        logger.info("pmo_created", pmo_id=pmo.id, code=pmo.code)
        return pmo

    async def update_pmo(self, id: int, data: dict) -> PMO:
        if data.get("status") == "closed":
            await self.delete_pmo(id)
            return await self.get_pmo(id)
        pmo = await self.get_pmo(id)
        updated = await self.repo.update(pmo, data)
        logger.info("pmo_updated", pmo_id=id)
        return updated

    async def delete_pmo(self, id: int) -> None:
        pmo = await self.get_pmo(id)
        pmo.status = "closed"
        self.session.add(pmo)
        today = date.today()
        stmt = (
            select(PMOMember)
            .where(PMOMember.pmo_id == id)
            .where(self._active_member_clause(today))
            .with_for_update()
        )
        members = list((await self.session.execute(stmt)).scalars().all())
        for member in members:
            member.to_date = today
            self.session.add(member)
        await self.session.flush()
        logger.info("pmo_closed", pmo_id=id, closed_members=len(members))

    # ── Members ────────────────────────────────────────────────────────

    async def list_members(self, pmo_id: int) -> list[dict]:
        await self.get_pmo(pmo_id)
        stmt = (
            select(PMOMember, Employee, Position)
            .join(Employee, PMOMember.employee_id == Employee.id)
            .outerjoin(Position, Employee.position_id == Position.id)
            .where(PMOMember.pmo_id == pmo_id)
            .order_by(PMOMember.to_date.is_not(None), PMOMember.from_date.desc(), Employee.last_name)
        )
        result = await self.session.execute(stmt)
        rows = result.all()
        return [
            {
                "id": m.id,
                "pmo_id": m.pmo_id,
                "employee_id": m.employee_id,
                "employee_name": f"{e.first_name} {e.last_name}",
                "employee_email": e.email,
                "primary_position": p.title if p else None,
                "position_in_pmo": m.position_in_pmo,
                "membership_type": m.membership_type,
                "allocation_percent": m.allocation_percent,
                "is_primary": m.is_primary,
                "from_date": m.from_date.isoformat() if m.from_date else None,
                "to_date": m.to_date.isoformat() if m.to_date else None,
            }
            for m, e, p in rows
        ]

    def _active_member_clause(self, today: date):
        return and_(
            PMOMember.from_date <= today,
            or_(PMOMember.to_date.is_(None), PMOMember.to_date >= today),
        )

    def _validate_member_dates(self, from_date: date, to_date: date | None) -> None:
        if to_date is not None and to_date < from_date:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="to_date must be >= from_date",
            )

    async def _assert_no_active_duplicate(
        self,
        *,
        pmo_id: int,
        employee_id: int,
        exclude_member_id: int | None = None,
    ) -> None:
        today = date.today()
        stmt = (
            select(PMOMember)
            .where(PMOMember.pmo_id == pmo_id)
            .where(PMOMember.employee_id == employee_id)
            .where(self._active_member_clause(today))
            .with_for_update()
        )
        if exclude_member_id is not None:
            stmt = stmt.where(PMOMember.id != exclude_member_id)
        existing = (await self.session.execute(stmt)).scalars().first()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Employee is already an active member of this PMO",
            )

    async def _assert_no_active_primary(
        self,
        *,
        pmo_id: int,
        exclude_member_id: int | None = None,
    ) -> None:
        today = date.today()
        stmt = (
            select(PMOMember)
            .where(PMOMember.pmo_id == pmo_id)
            .where(PMOMember.is_primary == True)  # noqa: E712
            .where(self._active_member_clause(today))
            .with_for_update()
        )
        if exclude_member_id is not None:
            stmt = stmt.where(PMOMember.id != exclude_member_id)
        existing = (await self.session.execute(stmt)).scalars().first()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="PMO already has a primary member",
            )

    async def _get_member(self, pmo_id: int, member_id: int) -> PMOMember:
        stmt = select(PMOMember).where(PMOMember.id == member_id, PMOMember.pmo_id == pmo_id)
        member = (await self.session.execute(stmt)).scalar_one_or_none()
        if not member:
            raise HTTPException(status_code=404, detail="Member not found in this PMO")
        return member

    async def add_member(self, pmo_id: int, data: dict, *, actor_user_id: int | None = None) -> tuple[PMOMember, int]:
        pmo = await self.get_pmo(pmo_id)
        if pmo.status == "closed":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Cannot add members to a closed PMO")
        # Verify employee exists
        emp = await self.session.get(Employee, data["employee_id"])
        if not emp:
            raise HTTPException(status_code=404, detail="Employee not found")

        from_date = data.get("from_date") or date.today()
        to_date = data.get("to_date")
        self._validate_member_dates(from_date, to_date)
        if from_date <= date.today() and (to_date is None or to_date >= date.today()):
            await self._assert_no_active_duplicate(pmo_id=pmo_id, employee_id=data["employee_id"])
            if data.get("is_primary", False):
                await self._assert_no_active_primary(pmo_id=pmo_id)

        member = PMOMember(
            pmo_id=pmo_id,
            employee_id=data["employee_id"],
            membership_type=data.get("membership_type", "permanent"),
            position_in_pmo=data.get("position_in_pmo"),
            from_date=from_date,
            to_date=to_date,
            allocation_percent=data.get("allocation_percent", 100),
            is_primary=data.get("is_primary", False),
        )
        self.session.add(member)
        await self.session.flush()
        await self.session.refresh(member)
        total = await self.employee_total_allocation(member.employee_id)
        logger.info(
            "pmo_member_added",
            pmo_id=pmo_id,
            employee_id=data["employee_id"],
            actor_user_id=actor_user_id,
            allocation_total=total,
        )
        return member, total

    async def update_member(
        self,
        pmo_id: int,
        member_id: int,
        data: dict,
        *,
        actor_user_id: int | None = None,
    ) -> tuple[PMOMember, int]:
        member = await self._get_member(pmo_id, member_id)
        employee_id = data.get("employee_id", member.employee_id)
        if employee_id != member.employee_id:
            emp = await self.session.get(Employee, employee_id)
            if not emp:
                raise HTTPException(status_code=404, detail="Employee not found")

        from_date = data.get("from_date", member.from_date)
        to_date = data.get("to_date", member.to_date)
        self._validate_member_dates(from_date, to_date)

        will_be_active = from_date <= date.today() and (to_date is None or to_date >= date.today())
        if will_be_active:
            await self._assert_no_active_duplicate(
                pmo_id=pmo_id,
                employee_id=employee_id,
                exclude_member_id=member_id,
            )
            if data.get("is_primary", member.is_primary):
                await self._assert_no_active_primary(pmo_id=pmo_id, exclude_member_id=member_id)

        for key, value in data.items():
            if hasattr(member, key):
                setattr(member, key, value)
        self.session.add(member)
        await self.session.flush()
        await self.session.refresh(member)
        total = await self.employee_total_allocation(member.employee_id)
        logger.info(
            "pmo_member_updated",
            pmo_id=pmo_id,
            member_id=member_id,
            actor_user_id=actor_user_id,
            allocation_total=total,
        )
        return member, total

    async def remove_member(self, pmo_id: int, member_id: int) -> None:
        member = await self._get_member(pmo_id, member_id)
        if member.to_date is None or member.to_date >= date.today():
            member.to_date = date.today() if member.from_date <= date.today() else member.from_date
            self.session.add(member)
        await self.session.flush()

    async def employee_total_allocation(self, employee_id: int) -> int:
        today = date.today()
        stmt = (
            select(func.coalesce(func.sum(PMOMember.allocation_percent), 0))
            .select_from(PMOMember)
            .join(PMO, PMOMember.pmo_id == PMO.id)
            .where(PMOMember.employee_id == employee_id)
            .where(PMO.status == "active")
            .where(self._active_member_clause(today))
        )
        return int((await self.session.execute(stmt)).scalar_one())

    async def get_employee_pmos(self, employee_id: int) -> list[dict]:
        if not await self.session.get(Employee, employee_id):
            raise HTTPException(status_code=404, detail="Employee not found")
        today = date.today()
        stmt = (
            select(PMOMember, PMO)
            .join(PMO, PMOMember.pmo_id == PMO.id)
            .where(PMOMember.employee_id == employee_id)
            .where(PMO.status == "active")
            .where(self._active_member_clause(today))
            .order_by(PMO.name.asc())
        )
        rows = (await self.session.execute(stmt)).all()
        return [
            {
                "pmo_id": pmo.id,
                "pmo_name": pmo.name,
                "pmo_code": pmo.code,
                "pmo_status": pmo.status,
                "membership_type": member.membership_type,
                "position_in_pmo": member.position_in_pmo,
                "allocation_percent": member.allocation_percent,
                "is_primary": member.is_primary,
                "from_date": member.from_date.isoformat() if member.from_date else None,
                "to_date": member.to_date.isoformat() if member.to_date else None,
            }
            for member, pmo in rows
        ]

    # ── PMO org-chart (for Фича 3 integration) ────────────────────────

    async def get_pmo_org_chart(self, pmo_id: int) -> dict:
        pmo = await self.get_pmo(pmo_id)
        members = await self.list_members(pmo_id)

        nodes = [
            {
                "id": f"pmo_{pmo.id}",
                "label": pmo.name,
                "type": "pmo",
                "unit_type": "pmo",
                "level": None,
                "weight": None,
                "meta": {"code": pmo.code, "status": pmo.status},
            }
        ]
        edges = []

        for m in members:
            nodes.append({
                "id": f"emp_{m['employee_id']}",
                "label": m["employee_name"],
                "type": "employee",
                "unit_type": None,
                "level": None,
                "weight": None,
                "meta": {
                    "membership_type": m["membership_type"],
                    "position_title": m["position_in_pmo"] or m["primary_position"],
                    "allocation_percent": m["allocation_percent"],
                    "is_primary": m["is_primary"],
                },
            })
            edges.append({
                "source": f"pmo_{pmo.id}",
                "target": f"emp_{m['employee_id']}",
                "relation_type": m["membership_type"],
            })

        return {"nodes": nodes, "edges": edges}
