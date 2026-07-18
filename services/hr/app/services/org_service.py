"""OrgService — subordination matrix, org tree, reporting relations CRUD."""

from datetime import date
from typing import Literal

import structlog
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.department import Department
from app.models.employee import Employee
from app.models.level_threshold import LevelThreshold
from app.models.org_settings import OrgSettings
from app.models.position import Position
from app.models.reporting_relation import ReportingRelation
from app.repositories.base_repo import BaseRepository
from app.services.translation_service import build_translated_org_tree

logger = structlog.get_logger()

RelationType = Literal["direct", "functional", "project"]
DeletionStrategy = Literal["block", "reassign_to_parent", "cascade"]


class OrgService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.dept_repo = BaseRepository(Department, session)
        self.pos_repo = BaseRepository(Position, session)
        self.rel_repo = BaseRepository(ReportingRelation, session)

    # ── Org settings ──────────────────────────────────────────────────

    async def get_deletion_strategy(self) -> DeletionStrategy:
        stmt = select(OrgSettings).where(OrgSettings.key == "deletion_strategy")
        result = await self.session.execute(stmt)
        setting = result.scalar_one_or_none()
        val = setting.value if setting else "block"
        if val not in ("block", "reassign_to_parent", "cascade"):
            return "block"
        return val  # type: ignore[return-value]

    async def set_deletion_strategy(self, strategy: DeletionStrategy) -> None:
        stmt = select(OrgSettings).where(OrgSettings.key == "deletion_strategy")
        result = await self.session.execute(stmt)
        setting = result.scalar_one_or_none()
        if setting:
            setting.value = strategy
            self.session.add(setting)
        else:
            self.session.add(OrgSettings(key="deletion_strategy", value=strategy))
        await self.session.flush()

    # ── Department deletion with configurable strategy ─────────────────

    async def delete_department(self, id: int) -> None:
        dept = await self.dept_repo.get(id)
        if not dept:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Department not found")

        children = await self._get_children(dept.path)
        if children:
            strategy = await self.get_deletion_strategy()
            if strategy == "block":
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Cannot delete '{dept.name}': has {len(children)} sub-unit(s). "
                           "Change deletion_strategy in org settings to allow cascade or reassign.",
                )
            elif strategy == "reassign_to_parent":
                parent_path = ".".join(dept.path.split(".")[:-1])
                parent = await self._get_dept_by_path(parent_path)
                parent_id = parent.id if parent else None
                for child in children:
                    # Re-root child one level up in the ltree
                    new_path = parent_path + "." + child.path.split(".")[-1] if parent_path else child.path.split(".")[-1]
                    child.path = new_path
                    if parent_id:
                        child.description = child.description  # touch to mark dirty
                    self.session.add(child)
            # cascade: FK ondelete is not set on departments, so delete children recursively
            elif strategy == "cascade":
                for child in children:
                    await self.session.delete(child)

        await self.session.delete(dept)
        await self.session.flush()
        logger.info("department_deleted", department_id=id, strategy=await self.get_deletion_strategy())

    async def _get_children(self, path: str) -> list[Department]:
        # Direct children only: path starts with parent_path + "." and has no further dots
        prefix = path + "."
        stmt = select(Department).where(Department.path.like(prefix + "%"))
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def _get_dept_by_path(self, path: str) -> Department | None:
        stmt = select(Department).where(Department.path == path)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    # ── Reporting relations ────────────────────────────────────────────

    async def add_relation(
        self,
        superior_id: int,
        subordinate_id: int,
        relation_type: RelationType,
        effective_from: date | None = None,
        effective_to: date | None = None,
    ) -> ReportingRelation:
        if superior_id == subordinate_id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="A position cannot be subordinate to itself",
            )
        # Check duplicate
        stmt = select(ReportingRelation).where(
            ReportingRelation.superior_position_id == superior_id,
            ReportingRelation.subordinate_position_id == subordinate_id,
            ReportingRelation.relation_type == relation_type,
        )
        existing = (await self.session.execute(stmt)).scalar_one_or_none()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This reporting relation already exists",
            )
        rel = await self.rel_repo.create({
            "superior_position_id": superior_id,
            "subordinate_position_id": subordinate_id,
            "relation_type": relation_type,
            "effective_from": effective_from or date.today(),
            "effective_to": effective_to,
        })
        logger.info("reporting_relation_added", superior=superior_id, subordinate=subordinate_id)
        return rel

    async def remove_relation(self, relation_id: int) -> None:
        rel = await self.rel_repo.get(relation_id)
        if not rel:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Relation not found")
        await self.rel_repo.delete(rel)

    async def get_relations_for_unit(self, unit_id: int) -> list[ReportingRelation]:
        """All relations where any position belongs to the given department."""
        stmt = (
            select(ReportingRelation)
            .join(Position, ReportingRelation.superior_position_id == Position.id)
            .where(Position.department_id == unit_id)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    # ── Subordination matrix ───────────────────────────────────────────

    async def get_subordination_matrix(self, unit_id: int | None = None) -> dict:
        """
        Returns matrix data: list of superior positions (rows),
        list of subordinate positions (cols), and relation cells.
        """
        stmt = select(ReportingRelation)
        if unit_id is not None:
            # Filter to relations where superior belongs to this unit
            stmt = (
                stmt
                .join(Position, ReportingRelation.superior_position_id == Position.id)
                .where(Position.department_id == unit_id)
            )
        result = await self.session.execute(stmt)
        relations = list(result.scalars().all())

        superior_ids = list({r.superior_position_id for r in relations})
        subordinate_ids = list({r.subordinate_position_id for r in relations})
        all_ids = list(set(superior_ids + subordinate_ids))

        if not all_ids:
            return {"superiors": [], "subordinates": [], "cells": []}

        pos_stmt = select(Position).where(Position.id.in_(all_ids))
        pos_result = await self.session.execute(pos_stmt)
        pos_map = {p.id: p for p in pos_result.scalars().all()}

        def pos_summary(p: Position) -> dict:
            return {"id": p.id, "title": p.title, "weight": p.weight, "level": p.level}

        cells = [
            {
                "superior_position_id": r.superior_position_id,
                "subordinate_position_id": r.subordinate_position_id,
                "relation_type": r.relation_type,
                "effective_from": r.effective_from.isoformat() if r.effective_from else None,
                "effective_to": r.effective_to.isoformat() if r.effective_to else None,
            }
            for r in relations
        ]

        return {
            "superiors": [pos_summary(pos_map[i]) for i in superior_ids if i in pos_map],
            "subordinates": [pos_summary(pos_map[i]) for i in subordinate_ids if i in pos_map],
            "cells": cells,
        }

    # ── Org tree (for Фича 3) ─────────────────────────────────────────

    async def get_org_tree(
        self,
        root_id: int | None,
        depth: int,
        mode: Literal["positions", "employees", "both"],
        lang: Literal["ru", "en"] = "ru",
    ) -> dict:
        """Build node/edge graph for React Flow rendering."""
        # Fetch all active departments
        dept_stmt = (
            select(Department)
            .where(Department.is_active == True)  # noqa: E712
            .order_by(Department.path.asc())
        )
        if root_id is not None:
            root = await self.dept_repo.get(root_id)
            if not root:
                raise HTTPException(status_code=404, detail="Root unit not found")
            dept_stmt = dept_stmt.where(Department.path.like(root.path + "%"))

        dept_result = await self.session.execute(dept_stmt)
        departments = list(dept_result.scalars().all())

        # Filter by depth relative to root
        root_depth = len(root.path.split(".")) if root_id else 0
        if root_id:
            departments = [
                d for d in departments
                if len(d.path.split(".")) - root_depth <= depth
            ]

        nodes: list[dict] = []
        edges: list[dict] = []

        manager_ids = [d.manager_id for d in departments if d.manager_id is not None]
        managers_by_id: dict[int, Employee] = {}
        if manager_ids:
            manager_result = await self.session.execute(
                select(Employee).where(
                    Employee.id.in_(manager_ids),
                    Employee.status == "active",
                    Employee.is_deleted == False,  # noqa: E712
                )
            )
            managers_by_id = {manager.id: manager for manager in manager_result.scalars().all()}
        manager_position_to_dept: dict[int, int] = {}
        for dept in departments:
            if dept.manager_id is None:
                continue
            manager = managers_by_id.get(dept.manager_id)
            if manager and manager.position_id:
                manager_position_to_dept[manager.position_id] = dept.id

        dept_nodes_by_id: dict[int, dict] = {}

        # Department nodes — emitted only when the caller asked to see them.
        # `mode="positions"` is a pure people/reporting chart: department info
        # is folded into the head's position card, not shown as a separate box.
        if mode != "positions":
            for dept in departments:
                manager = managers_by_id.get(dept.manager_id) if dept.manager_id is not None else None
                dept_node = {
                    "id": f"dept_{dept.id}",
                    "label": dept.name,
                    "type": "department",
                    "unit_type": dept.unit_type,
                    "level": len(dept.path.split(".")),
                    "weight": None,
                    "meta": {
                        "id": dept.id,
                        "path": dept.path,
                        "manager_id": manager.id if manager else None,
                        "manager_name": (
                            f"{manager.first_name} {manager.last_name}".strip()
                            if manager else None
                        ),
                        "manager_avatar_url": manager.avatar_url if manager else None,
                        "manager_position_id": manager.position_id if manager else None,
                    },
                }
                nodes.append(dept_node)
                dept_nodes_by_id[dept.id] = dept_node
                # Edge to parent department
                parts = dept.path.split(".")
                if len(parts) > 1:
                    parent_path = ".".join(parts[:-1])
                    parent = next((d for d in departments if d.path == parent_path), None)
                    if parent:
                        edges.append({
                            "source": f"dept_{parent.id}",
                            "target": f"dept_{dept.id}",
                            "relation_type": "structural",
                        })

        if mode in ("positions", "both"):
            dept_ids = [d.id for d in departments]
            threshold_result = await self.session.execute(select(LevelThreshold))
            level_colors = {
                threshold.level_number: threshold.color
                for threshold in threshold_result.scalars().all()
                if threshold.color
            }
            pos_stmt = (
                select(Position)
                .where(
                    Position.department_id.in_(dept_ids),
                    Position.is_active == True,  # noqa: E712
                )
                .order_by(Position.level.asc(), Position.weight.asc(), Position.title.asc())
            )
            pos_result = await self.session.execute(pos_stmt)
            positions = list(pos_result.scalars().all())
            positions_by_id = {p.id: p for p in positions}
            positions_by_dept: dict[int, list[Position]] = {}
            for pos in positions:
                positions_by_dept.setdefault(pos.department_id, []).append(pos)

            # Active employees occupying these positions, indexed by position_id
            # so the position node can carry holder name(s) without duplicating
            # employees as separate nodes.
            holders_by_pos: dict[int, list[Employee]] = {}
            if positions:
                pos_ids = [p.id for p in positions]
                holder_stmt = select(Employee).where(
                    Employee.position_id.in_(pos_ids),
                    Employee.status == "active",
                    Employee.is_deleted == False,  # noqa: E712
                )
                for emp in (await self.session.execute(holder_stmt)).scalars().all():
                    holders_by_pos.setdefault(emp.position_id, []).append(emp)

            # Resolve a single reporting parent per position. We pick the first
            # 'direct' relation if present, falling back to any other type. This
            # collapses dept→position membership and pos→pos reporting into a
            # single tree edge per position so the chart matches a classic
            # "boxes-and-lines" org-chart shape rather than doubling edges.
            superior_by_pos: dict[int, ReportingRelation] = {}
            pos_ids = [p.id for p in positions]
            merged_manager_pos_ids = {
                pos_id
                for pos_id, dept_id in manager_position_to_dept.items()
                if any(p.id == pos_id and p.department_id == dept_id for p in positions)
            }
            visible_pos_ids = set(pos_ids) - merged_manager_pos_ids
            if pos_ids:
                rel_stmt = select(ReportingRelation).where(
                    ReportingRelation.subordinate_position_id.in_(pos_ids)
                )
                for rel in (await self.session.execute(rel_stmt)).scalars().all():
                    existing = superior_by_pos.get(rel.subordinate_position_id)
                    if existing is None or (
                        rel.relation_type == "direct" and existing.relation_type != "direct"
                    ):
                        superior_by_pos[rel.subordinate_position_id] = rel

            superior_counts_by_dept: dict[int, dict[int, int]] = {}
            for rel in superior_by_pos.values():
                superior = positions_by_id.get(rel.superior_position_id)
                subordinate = positions_by_id.get(rel.subordinate_position_id)
                if superior is None or subordinate is None:
                    continue
                if superior.department_id != subordinate.department_id:
                    continue
                counts = superior_counts_by_dept.setdefault(superior.department_id, {})
                counts[superior.id] = counts.get(superior.id, 0) + 1

            def is_lead_title(title: str) -> bool:
                title_lower = title.lower()
                return any(
                    marker in title_lower
                    for marker in (
                        "lead",
                        "head",
                        "chief",
                        "manager",
                        "director",
                        "руковод",
                        "началь",
                        "тимлид",
                        "лид",
                    )
                )

            def choose_department_lead(dept_id: int) -> tuple[Position, Employee] | None:
                candidates = [
                    pos
                    for pos in positions_by_dept.get(dept_id, [])
                    if holders_by_pos.get(pos.id)
                ]
                if not candidates:
                    return None
                superior_counts = superior_counts_by_dept.get(dept_id, {})
                relation_candidates = [
                    pos
                    for pos in candidates
                    if superior_counts.get(pos.id, 0) > 0
                ]
                title_candidates = [pos for pos in candidates if is_lead_title(pos.title)]
                pool = relation_candidates or title_candidates or candidates
                pool.sort(key=lambda p: (p.level, p.weight, p.title))
                lead_pos = pool[0]
                return lead_pos, holders_by_pos[lead_pos.id][0]

            for dept in departments:
                if dept.id in manager_position_to_dept.values():
                    continue
                lead = choose_department_lead(dept.id)
                if lead is None:
                    continue
                lead_pos, lead_employee = lead
                manager_position_to_dept[lead_pos.id] = dept.id
                dept_node = dept_nodes_by_id.get(dept.id)
                if dept_node is not None:
                    dept_node["meta"].update({
                        "manager_id": lead_employee.id,
                        "manager_name": f"{lead_employee.first_name} {lead_employee.last_name}".strip(),
                        "manager_avatar_url": lead_employee.avatar_url,
                        "manager_position_id": lead_pos.id,
                        "manager_position_title": lead_pos.title,
                        "manager_source": "inferred",
                    })

            merged_manager_pos_ids = {
                pos_id
                for pos_id, dept_id in manager_position_to_dept.items()
                if any(p.id == pos_id and p.department_id == dept_id for p in positions)
            }
            visible_pos_ids = set(pos_ids) - merged_manager_pos_ids

            # ── Helpers used by both `positions` and `both` modes ──────────
            #
            # `head_pos_id_by_dept` answers: which position card represents the
            # leadership of department X? Used to route reports through the
            # head when there is no explicit ReportingRelation.
            head_pos_id_by_dept: dict[int, int] = {
                dept_id: pos_id
                for pos_id, dept_id in manager_position_to_dept.items()
            }
            # `dept_by_id` and `parent_dept_id` for ltree-based fallback lookup.
            dept_by_id = {d.id: d for d in departments}
            dept_by_path = {d.path: d for d in departments}

            def parent_dept_id_for(dept_id: int) -> int | None:
                d = dept_by_id.get(dept_id)
                if d is None:
                    return None
                parts = d.path.split(".")
                if len(parts) <= 1:
                    return None
                parent = dept_by_path.get(".".join(parts[:-1]))
                return parent.id if parent else None

            def fallback_parent_pos_id(pos: Position) -> int | None:
                """Pos→pos parent inferred from the dept hierarchy.

                For a non-head position: its parent is the head of the same dept.
                For a head position: its parent is the head of the parent dept.
                """
                dept_head = head_pos_id_by_dept.get(pos.department_id)
                if dept_head is not None and dept_head != pos.id:
                    return dept_head
                # Walk up the dept tree until we find a head different from us.
                current_dept_id: int | None = pos.department_id
                while current_dept_id is not None:
                    current_dept_id = parent_dept_id_for(current_dept_id)
                    if current_dept_id is None:
                        return None
                    candidate = head_pos_id_by_dept.get(current_dept_id)
                    if candidate is not None and candidate != pos.id:
                        return candidate
                return None

            for pos in positions:
                # In `both` mode the head of a dept is folded into its dept
                # card, so we skip emitting a duplicate position node for it.
                if mode == "both" and pos.id in merged_manager_pos_ids:
                    continue
                holders = holders_by_pos.get(pos.id, [])
                primary = holders[0] if holders else None
                heads_dept = (
                    dept_by_id.get(manager_position_to_dept.get(pos.id))
                    if pos.id in manager_position_to_dept
                    else None
                )
                own_dept = dept_by_id.get(pos.department_id)
                nodes.append({
                    "id": f"pos_{pos.id}",
                    "label": pos.title,
                    "type": "position",
                    "unit_type": None,
                    "level": pos.level,
                    "weight": pos.weight,
                    "meta": {
                        "grade": pos.grade,
                        "department_id": pos.department_id,
                        "department_name": own_dept.name if own_dept else None,
                        "department_path": own_dept.path if own_dept else None,
                        "level_color": level_colors.get(pos.level),
                        "is_phantom": primary is None,
                        # Set when the holder is the manager of a department —
                        # the card surfaces "руководит отделом X".
                        "heads_department_id": heads_dept.id if heads_dept else None,
                        "heads_department_name": heads_dept.name if heads_dept else None,
                        # Holder enrichment — keeps the graph compact (one node
                        # per position) while still surfacing who occupies it.
                        "holder_id": primary.id if primary else None,
                        "holder_name": (
                            f"{primary.first_name} {primary.last_name}".strip()
                            if primary else None
                        ),
                        "holder_email": primary.email if primary else None,
                        "holder_phone": primary.phone if primary else None,
                        "holder_avatar_url": primary.avatar_url if primary else None,
                        "holder_count": len(holders),
                        "holders": [
                            {
                                "id": e.id,
                                "name": f"{e.first_name} {e.last_name}".strip(),
                                "avatar_url": e.avatar_url,
                            }
                            for e in holders
                        ],
                    },
                })

                rel = superior_by_pos.get(pos.id)

                if mode == "positions":
                    # Pure people graph: every edge is pos→pos. If there's no
                    # explicit reporting relation, fall back to the dept-tree
                    # head chain so the chart stays connected.
                    superior_id: int | None = None
                    relation_type = "direct"
                    if rel is not None:
                        superior_id = rel.superior_position_id
                        relation_type = rel.relation_type
                    else:
                        superior_id = fallback_parent_pos_id(pos)
                        relation_type = "direct"
                    if superior_id is not None and superior_id != pos.id:
                        edges.append({
                            "source": f"pos_{superior_id}",
                            "target": f"pos_{pos.id}",
                            "relation_type": relation_type,
                        })
                    # else: top of the tree — no incoming edge.
                else:  # mode == "both" — keep dept boxes for context
                    if rel is not None:
                        manager_dept_id = manager_position_to_dept.get(rel.superior_position_id)
                        if manager_dept_id is not None:
                            edges.append({
                                "source": f"dept_{manager_dept_id}",
                                "target": f"pos_{pos.id}",
                                "relation_type": rel.relation_type,
                            })
                        elif rel.superior_position_id in visible_pos_ids:
                            edges.append({
                                "source": f"pos_{rel.superior_position_id}",
                                "target": f"pos_{pos.id}",
                                "relation_type": rel.relation_type,
                            })
                        else:
                            edges.append({
                                "source": f"dept_{pos.department_id}",
                                "target": f"pos_{pos.id}",
                                "relation_type": "membership",
                            })
                    else:
                        edges.append({
                            "source": f"dept_{pos.department_id}",
                            "target": f"pos_{pos.id}",
                            "relation_type": "membership",
                        })
        if mode == "employees":
            dept_ids = [d.id for d in departments]
            emp_stmt = (
                select(Employee)
                .where(
                    Employee.department_id.in_(dept_ids),
                    Employee.status == "active",
                    Employee.is_deleted == False,  # noqa: E712
                )
                .order_by(Employee.last_name.asc(), Employee.first_name.asc())
            )
            emp_result = await self.session.execute(emp_stmt)
            employees = list(emp_result.scalars().all())

            for emp in employees:
                nodes.append({
                    "id": f"emp_{emp.id}",
                    "label": f"{emp.first_name} {emp.last_name}",
                    "type": "employee",
                    "unit_type": None,
                    "level": None,
                    "weight": None,
                    "meta": {
                        "avatar_url": emp.avatar_url,
                        "department_id": emp.department_id,
                        "position_id": emp.position_id,
                    },
                })
                parent = f"pos_{emp.position_id}" if mode == "both" and emp.position_id else f"dept_{emp.department_id}"
                edges.append({
                    "source": parent,
                    "target": f"emp_{emp.id}",
                    "relation_type": "employment",
                })

        tree = {"nodes": nodes, "edges": edges}
        if lang == "en":
            translated = await build_translated_org_tree(tree, "en")
            if translated is not None:
                return translated
        return tree
