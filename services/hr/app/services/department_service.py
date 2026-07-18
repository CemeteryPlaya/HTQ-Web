"""Department service — business logic for department management."""

import structlog
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.department import Department
from app.repositories.department_repo import DepartmentRepository
from app.schemas.department import DepartmentCreate, DepartmentUpdate, DepartmentTree
from app.workers.actors import department_deleted, department_upserted

logger = structlog.get_logger()


def _department_event_payload(dept: Department) -> dict:
    return {
        "id": dept.id,
        "name": dept.name,
        "path": dept.path,
        "is_active": dept.is_active,
    }


class DepartmentService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = DepartmentRepository(session)

    async def list_departments(self) -> list[Department]:
        # Eager-load positions so DepartmentWithPositions can serialize them
        # without triggering an async lazy-load.
        return await self.repo.get_all_active_with_positions()

    async def get_department(self, id: int) -> Department:
        dept = await self.repo.get(id)
        if not dept:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Department not found")
        return dept

    async def get_tree(self) -> list[DepartmentTree]:
        """Build a nested department tree from flat list."""
        all_depts = await self.repo.get_all_active()
        return _build_tree(all_depts)

    async def get_children(self, id: int) -> list[Department]:
        dept = await self.get_department(id)
        return await self.repo.get_children(dept.path)

    async def get_employees(self, id: int) -> list:
        dept = await self.repo.get_employees(id)
        if not dept:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Department not found")
        return dept.employees

    async def create_department(self, data: DepartmentCreate) -> Department:
        import re
        import time
        from uuid import uuid4

        path = data.path
        if not path:
            # Simple transliteration for Russian chars
            translit = {
                'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'e',
                'ж': 'zh', 'з': 'z', 'и': 'i', 'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm',
                'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u',
                'ф': 'f', 'х': 'h', 'ц': 'ts', 'ч': 'ch', 'ш': 'sh', 'щ': 'shch',
                'ъ': '', 'ы': 'y', 'ь': '', 'э': 'e', 'ю': 'yu', 'я': 'ya'
            }
            slug = ''.join(translit.get(c, c) for c in data.name.lower())
            slug = re.sub(r'[^a-z0-9]+', '_', slug).strip('_')
            if not slug:
                slug = f"dept_{str(uuid4())[:8]}"

            if getattr(data, 'parent_id', None):
                parent = await self.get_department(data.parent_id)
                path = f"{parent.path}.{slug}"
            else:
                path = slug

        # Ensure uniqueness
        existing = await self.repo.get_by_path(path)
        if existing:
            path = f"{path}_{int(time.time())}"

        dump = data.model_dump(exclude={"parent_id"}, exclude_none=True)
        dump["path"] = path

        dept = await self.repo.create(dump)
        department_upserted.send(_department_event_payload(dept))
        logger.info("department_created", department_id=dept.id, path=dept.path)
        return dept

    async def update_department(self, id: int, data: DepartmentUpdate) -> Department:
        dept = await self.get_department(id)
        patch = data.model_dump(exclude_none=True)
        updated = await self.repo.update(dept, patch)
        department_upserted.send(_department_event_payload(updated))
        logger.info("department_updated", department_id=id)
        return updated

    async def delete_department(self, id: int, *, cascade: bool = False) -> None:
        from sqlalchemy import delete as sa_delete, func, select

        from app.models.employee import Employee
        from app.models.pmo import PMOMember
        from app.models.position import Position
        from app.models.reporting_relation import ReportingRelation

        dept = await self.get_department(id)

        children = await self.repo.get_children(dept.path)
        position_count = (
            await self.session.execute(
                select(func.count(Position.id)).where(Position.department_id == id)
            )
        ).scalar_one()
        employee_count = (
            await self.session.execute(
                select(func.count(Employee.id)).where(
                    Employee.department_id == id,
                    Employee.is_deleted == False,  # noqa: E712
                )
            )
        ).scalar_one()

        blockers = {
            "sub_departments": len(children),
            "positions": position_count,
            "employees": employee_count,
        }
        has_blockers = any(blockers.values())

        if has_blockers and not cascade:
            # Structured detail so the UI can render a precise confirmation
            # ("Удалить вместе с 3 должностями и 5 сотрудниками?") and re-issue
            # the request with cascade=true on confirm.
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "department_has_dependents",
                    "message": (
                        f"К подразделению «{dept.name}» привязаны другие записи. "
                        "Подтвердите каскадное удаление."
                    ),
                    "department": {"id": dept.id, "name": dept.name},
                    "blockers": blockers,
                },
            )

        if cascade and has_blockers:
            # Collect every department in the subtree (this dept + descendants)
            # via the existing ltree path: `path = X` OR `path LIKE 'X.%'`.
            subtree_paths_stmt = select(Department.id).where(
                (Department.path == dept.path)
                | (Department.path.like(dept.path + ".%"))
            )
            dept_ids = [row[0] for row in (await self.session.execute(subtree_paths_stmt)).all()]
            if not dept_ids:
                dept_ids = [dept.id]

            # Positions to clear out (FK targets of reporting relations and PMO).
            position_ids_stmt = select(Position.id).where(Position.department_id.in_(dept_ids))
            position_ids = [row[0] for row in (await self.session.execute(position_ids_stmt)).all()]

            # Employees to clear out (FK targets of PMO members and dept manager).
            employee_ids_stmt = select(Employee.id).where(Employee.department_id.in_(dept_ids))
            employee_ids = [row[0] for row in (await self.session.execute(employee_ids_stmt)).all()]

            # 1. Drop reporting relations that touch any in-scope position.
            if position_ids:
                await self.session.execute(
                    sa_delete(ReportingRelation).where(
                        (ReportingRelation.superior_position_id.in_(position_ids))
                        | (ReportingRelation.subordinate_position_id.in_(position_ids))
                    )
                )

            # 2. Drop PMO memberships of in-scope employees.
            if employee_ids:
                await self.session.execute(
                    sa_delete(PMOMember).where(PMOMember.employee_id.in_(employee_ids))
                )

            # 3. Null out dept manager FK for in-scope departments before
            #    deleting employees — those are managers themselves.
            await self.session.execute(
                Department.__table__.update()
                .where(Department.id.in_(dept_ids))
                .values(manager_id=None)
            )
            # Also clear any manager_id elsewhere that points at one of our
            # employees (e.g. a parent dept whose head is being deleted).
            if employee_ids:
                await self.session.execute(
                    Department.__table__.update()
                    .where(Department.manager_id.in_(employee_ids))
                    .values(manager_id=None)
                )

            # 4. Hard-delete employees and positions.
            if employee_ids:
                await self.session.execute(
                    sa_delete(Employee).where(Employee.id.in_(employee_ids))
                )
            if position_ids:
                await self.session.execute(
                    sa_delete(Position).where(Position.id.in_(position_ids))
                )

            # 5. Drop child departments (deepest first so FK-less paths stay
            #    consistent). The dept itself stays — handled below by repo.
            child_ids = [d for d in dept_ids if d != dept.id]
            if child_ids:
                # Sort by path depth desc so leaves go first — guards against
                # any future FK constraint between departments.
                children_rows = (
                    await self.session.execute(
                        select(Department).where(Department.id.in_(child_ids))
                    )
                ).scalars().all()
                children_rows.sort(key=lambda d: -len(d.path.split(".")))
                for child in children_rows:
                    await self.session.delete(child)

            await self.session.flush()

        await self.repo.delete(dept)
        department_deleted.send({"id": id})
        logger.info(
            "department_deleted",
            department_id=id,
            cascade=cascade,
            blockers=blockers,
        )


def _build_tree(departments: list[Department]) -> list[DepartmentTree]:
    """Convert flat list of departments to nested tree using ltree paths."""
    from app.schemas.department import DepartmentTree as Tree

    tree_map: dict[int, Tree] = {}
    roots: list[Tree] = []

    # Build nodes
    for dept in departments:
        node = Tree.model_validate(dept)
        tree_map[dept.id] = node

    # Wire children via path prefix
    for dept in departments:
        node = tree_map[dept.id]
        parent_path = ".".join(dept.path.split(".")[:-1])
        parent = next((d for d in departments if d.path == parent_path), None)
        if parent and parent.id in tree_map:
            tree_map[parent.id].children.append(node)
        else:
            roots.append(node)

    return roots
