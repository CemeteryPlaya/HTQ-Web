"""Бизнес-логика организационной структуры — порт
services/hr/app/services/org_service.py (без ``delete_department`` — мёртвый
код исходника: ни один роутер его не зовёт, departments-роутер ходит в
``DepartmentService``/``apps.hr.services.department_service``) +
services/hr/app/services/translation_service.py (build_translated_org_tree).

Решения, зафиксированные при переносе (docs/plans/2026-07-20-hr-domain.md):

* Функции, а не класс ``OrgService`` — тот же стиль, что и у
  department_service.py/position_service.py этого порта (исходник был
  class-based только из-за DI сессии SQLAlchemy, здесь ORM синхронный и
  сессии нет).
* ``get_org_tree`` перенесён БУКВАЛЬНО, включая эвристику выбора руководителя
  отдела (``choose_department_lead``/``is_lead_title``), фолбэк-разрешение
  родителя должности (``fallback_parent_pos_id``) и «дыры» исходника, которые
  не чинятся молча при переносе:
  - ``root.path.like(root.path + "%")`` — без разделителя ``"."`` перед ``%``,
    поэтому формально матчит и отделы, чей path начинается с ЭТОЙ ЖЕ строки
    без точки (например root="it" матчит и гипотетический "itx");
  - ``if root_id:`` (truthy-проверка, а не ``is not None``) в двух местах;
  - ``mode == "both"`` внутри ветки ``mode == "employees"`` — всегда False
    (эта ветка не достижима при mode="employees"), но в исходнике условие
    именно такое.
* Перевод (D9, lang="en"): ``build_translated_org_tree`` пытается Google
  Translate, затем LibreTranslate; ключи/URL читаются через
  ``getattr(settings, ..., "")`` — в htqweb/settings их пока нет (граница
  задачи — только apps/hr/**, settings-модули не трогаем), поэтому функция
  ВСЕГДА no-op, пока кто-то не заведёт эти переменные — тот же паттерн
  выключенности, что и ``TRANSLATION_API_KEY=""`` в apps/cms/tasks.py.
  ``get_org_tree`` при недоступном переводе отдаёт исходное ru-дерево
  (буквально как исходник: ``if translated is not None: return translated``,
  иначе ``return tree``).
"""
from __future__ import annotations

import copy
import html
import logging
from datetime import date
from typing import Literal

import httpx
from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.http import Http404

from apps.hr.models import (
    Department,
    Employee,
    EmployeeReportingOverride,
    LevelThreshold,
    OrgSettings,
    Position,
    ReportingRelation,
)
from apps.hr.services import audit_service

logger = logging.getLogger(__name__)

RelationType = Literal["direct", "functional", "project"]
DeletionStrategy = Literal["block", "reassign_to_parent", "cascade"]
OrgLanguage = Literal["ru", "en"]

_DELETION_STRATEGIES = ("block", "reassign_to_parent", "cascade")


# ── исключения (структурированные — carries .detail, статус решает вьюха) ───

class RelationSelfReferential(Exception):
    """422: попытка сделать должность подчинённой самой себе."""

    detail = "A position cannot be subordinate to itself"

    def __init__(self) -> None:
        super().__init__(self.detail)


class RelationDuplicate(Exception):
    """409: такая связь (superior, subordinate, relation_type) уже есть."""

    detail = "This reporting relation already exists"

    def __init__(self) -> None:
        super().__init__(self.detail)


class RelationNotFound(Exception):
    """404: связь не найдена."""

    detail = "Relation not found"

    def __init__(self) -> None:
        super().__init__(self.detail)


class RelationCycle(Exception):
    """409: связь замкнула бы цепочку подчинения в кольцо.

    Обход циклов — забота сервиса, не БД: транзитивный цикл в Postgres
    выражается только рекурсивным CTE/триггером, а тут достаточно графового
    обхода на запись (см. ``_position_cycle_exists``/``_employee_cycle_exists``).
    """

    detail = "Эта связь замкнёт цепочку подчинения в кольцо"

    def __init__(self) -> None:
        super().__init__(self.detail)


class PositionNotFound(Exception):
    """404: должность (superior или subordinate) не существует.

    Не порт — исходная ``add_relation`` полагалась на FK и роняла голый 500
    на несуществующий id. Ручку теперь дёргает UI напрямую, 500 недопустим.
    """

    detail = "Position not found"

    def __init__(self) -> None:
        super().__init__(self.detail)


# ── исключения employee-relations (не порт, ново для персональных связей) ──

class EmployeeRelationSelfReferential(Exception):
    """422: сотрудник не может подчиняться сам себе."""

    detail = "Сотрудник не может подчиняться сам себе"

    def __init__(self) -> None:
        super().__init__(self.detail)


class EmployeeRelationDuplicate(Exception):
    """409: такая персональная связь (superior, subordinate, relation_type) уже есть."""

    detail = "Такая связь подчинения уже существует"

    def __init__(self) -> None:
        super().__init__(self.detail)


class EmployeeRelationNotFound(Exception):
    """404: персональная связь не найдена."""

    detail = "Связь подчинения не найдена"

    def __init__(self) -> None:
        super().__init__(self.detail)


class EmployeeAlreadyHasSuperior(Exception):
    """409: у сотрудника уже есть ПРЯМОЙ руководитель (частичный unique-констрейнт
    ``ux_employee_override_one_direct_superior`` допускает ровно одного).

    Несёт имя текущего руководителя и id существующей связи, чтобы UI мог
    предложить «заменить» вместо голого отказа.
    """

    def __init__(self, superior_name: str, relation_id: int) -> None:
        self.detail = f"У сотрудника уже есть прямой руководитель: {superior_name}"
        self.relation_id = relation_id
        super().__init__(self.detail)


class EmployeeNotFoundForRelation(Exception):
    """404: employee_id из тела запроса не существует или мягко удалён."""

    detail = "Employee not found"

    def __init__(self) -> None:
        super().__init__(self.detail)


class EmployeeNotActiveForRelation(Exception):
    """422: сотрудник не в статусе active — не годится ни в руководители,
    ни в подчинённые (иначе воспроизводим находку разведки: manager_id в
    БД есть, а в дереве узел молча становится null, потому что get_org_tree
    фильтрует managers/holders по status="active")."""

    detail = "Нельзя назначить неактивного или удалённого сотрудника"

    def __init__(self) -> None:
        super().__init__(self.detail)


class OrgDepartmentNotFound(Exception):
    """404: отдел не найден — для /org/departments/{id}/manager."""

    detail = "Department not found"

    def __init__(self) -> None:
        super().__init__(self.detail)


# ── сериализаторы ─────────────────────────────────────────────────────────

def serialize_relation(rel: ReportingRelation) -> dict:
    """RelationOut."""
    return {
        "id": rel.id,
        "superior_position_id": rel.superior_position_id,
        "subordinate_position_id": rel.subordinate_position_id,
        "relation_type": rel.relation_type,
        "effective_from": rel.effective_from.isoformat() if rel.effective_from else None,
        "effective_to": rel.effective_to.isoformat() if rel.effective_to else None,
    }


# ── org settings ────────────────────────────────────────────────────────────

def get_deletion_strategy() -> DeletionStrategy:
    setting = OrgSettings.objects.filter(key="deletion_strategy").first()
    val = setting.value if setting else "block"
    if val not in _DELETION_STRATEGIES:
        return "block"
    return val  # type: ignore[return-value]


def set_deletion_strategy(strategy: DeletionStrategy) -> None:
    setting = OrgSettings.objects.filter(key="deletion_strategy").first()
    if setting:
        setting.value = strategy
        setting.save(update_fields=["value"])
    else:
        OrgSettings.objects.create(key="deletion_strategy", value=strategy)


# ── reporting relations ─────────────────────────────────────────────────────

def _position_cycle_exists(superior_id: int, subordinate_id: int) -> bool:
    """DFS вверх от superior_id по УЖЕ существующим связям всех типов.

    Кросс-типовая проверка (не только внутри relation_type новой связи) —
    осознанный выбор: "A направляет B напрямую, B направляет A
    функционально" — тоже кольцо подчинения, просто разными словами, и
    путать пользователя такой "матричной" лазейкой не стоит.

    seen защищает и от уже существующих в данных циклов (их обход сам по
    себе не должен зациклиться), хотя после этой проверки новых таких
    появиться не должно.
    """
    parents: dict[int, list[int]] = {}
    for sub, sup in ReportingRelation.objects.values_list(
        "subordinate_position_id", "superior_position_id",
    ):
        parents.setdefault(sub, []).append(sup)

    stack = [superior_id]
    seen: set[int] = set()
    while stack:
        node = stack.pop()
        if node == subordinate_id:
            return True
        if node in seen:
            continue
        seen.add(node)
        stack.extend(parents.get(node, ()))
    return False


@transaction.atomic
def add_relation(
    *,
    superior_id: int,
    subordinate_id: int,
    relation_type: RelationType = "direct",
    effective_from: date | None = None,
    effective_to: date | None = None,
) -> ReportingRelation:
    if superior_id == subordinate_id:
        raise RelationSelfReferential()
    known_ids = set(
        Position.objects.filter(id__in=(superior_id, subordinate_id)).values_list("id", flat=True)
    )
    if {superior_id, subordinate_id} - known_ids:
        raise PositionNotFound()
    exists = ReportingRelation.objects.filter(
        superior_position_id=superior_id,
        subordinate_position_id=subordinate_id,
        relation_type=relation_type,
    ).exists()
    if exists:
        raise RelationDuplicate()
    if _position_cycle_exists(superior_id, subordinate_id):
        raise RelationCycle()
    rel = ReportingRelation.objects.create(
        superior_position_id=superior_id,
        subordinate_position_id=subordinate_id,
        relation_type=relation_type,
        effective_from=effective_from or date.today(),
        effective_to=effective_to,
    )
    return rel


def remove_relation(relation_id: int) -> None:
    rel = ReportingRelation.objects.filter(id=relation_id).first()
    if rel is None:
        raise RelationNotFound()
    rel.delete()


# ── employee reporting overrides (не порт, ручная правка орг-связей) ────────
#
# Персональный слой поверх ReportingRelation: сотрудник X подчиняется
# сотруднику Y независимо от связей их должностей. Приоритет разрешения —
# см. get_org_tree ниже: override -> ReportingRelation -> Department.manager
# -> эвристика по названию/пути.

def serialize_employee_relation(rel: EmployeeReportingOverride) -> dict:
    return {
        "id": rel.id,
        "superior_employee_id": rel.superior_id,
        "subordinate_employee_id": rel.subordinate_id,
        "superior_name": f"{rel.superior.first_name} {rel.superior.last_name}".strip(),
        "subordinate_name": f"{rel.subordinate.first_name} {rel.subordinate.last_name}".strip(),
        "relation_type": rel.relation_type,
        "note": rel.note,
        "created_at": rel.created_at.isoformat() if rel.created_at else None,
    }


def list_employee_relations(
    *, employee_id: int | None = None, department_id: int | None = None,
) -> list[dict]:
    qs = EmployeeReportingOverride.objects.select_related("superior", "subordinate")
    if employee_id is not None:
        qs = qs.filter(Q(superior_id=employee_id) | Q(subordinate_id=employee_id))
    if department_id is not None:
        qs = qs.filter(
            Q(superior__department_id=department_id) | Q(subordinate__department_id=department_id)
        )
    return [serialize_employee_relation(r) for r in qs.order_by("id")]


def _build_effective_employee_superiors() -> dict[int, int]:
    """Один руководитель на активного сотрудника — по ТОЙ ЖЕ лестнице
    приоритетов, что рисует get_org_tree:

    1) явный direct-override этого сотрудника;
    2) держатель вышестоящей должности (direct ReportingRelation, иначе
       любая) для должности сотрудника;
    3) Department.manager его отдела;
    4) Department.manager ближайшего отдела-предка по пути (path).

    Используется ТОЛЬКО для проверки циклов при добавлении override —
    отдельно от get_org_tree, чтобы не тащить сюда department-узлы/уровни/
    holders, которые для этой задачи не нужны.
    """
    employees = list(
        Employee.objects.filter(status="active", is_deleted=False)
        .values("id", "position_id", "department_id")
    )
    emp_ids = {e["id"] for e in employees}

    direct_override_superior: dict[int, int] = {}
    for sub, sup in EmployeeReportingOverride.objects.filter(
        relation_type="direct", subordinate_id__in=emp_ids,
    ).values_list("subordinate_id", "superior_id"):
        direct_override_superior.setdefault(sub, sup)

    superior_position: dict[int, int] = {}
    for sub_pos, sup_pos, rel_type in ReportingRelation.objects.order_by("id").values_list(
        "subordinate_position_id", "superior_position_id", "relation_type",
    ):
        existing = superior_position.get(sub_pos)
        if existing is None or rel_type == "direct":
            superior_position[sub_pos] = sup_pos

    # Первый активный держатель на должность — так же, как holders_by_pos
    # в get_org_tree выбирает primary = holders[0].
    holder_of_position: dict[int, int] = {}
    for e in sorted(employees, key=lambda e: e["id"]):
        holder_of_position.setdefault(e["position_id"], e["id"])

    dept_manager: dict[int, int] = dict(
        Department.objects.filter(manager_id__isnull=False, is_active=True)
        .values_list("id", "manager_id")
    )
    dept_path: dict[int, str] = dict(Department.objects.values_list("id", "path"))
    dept_by_path = {path: dept_id for dept_id, path in dept_path.items()}

    def nearest_ancestor_manager(department_id):
        current = department_id
        while current is not None:
            manager = dept_manager.get(current)
            if manager is not None and manager in emp_ids:
                return manager
            path = dept_path.get(current)
            if not path or "." not in path:
                return None
            current = dept_by_path.get(path.rsplit(".", 1)[0])
        return None

    effective: dict[int, int] = {}
    for e in employees:
        emp_id = e["id"]
        override_sup = direct_override_superior.get(emp_id)
        if override_sup is not None and override_sup in emp_ids:
            effective[emp_id] = override_sup
            continue
        sup_pos = superior_position.get(e["position_id"])
        holder = holder_of_position.get(sup_pos) if sup_pos is not None else None
        if holder is not None and holder != emp_id:
            effective[emp_id] = holder
            continue
        own_manager = dept_manager.get(e["department_id"])
        if own_manager is not None and own_manager in emp_ids and own_manager != emp_id:
            effective[emp_id] = own_manager
            continue
        ancestor_manager = nearest_ancestor_manager(e["department_id"])
        if ancestor_manager is not None and ancestor_manager != emp_id:
            effective[emp_id] = ancestor_manager
    return effective


def _employee_cycle_exists(superior_id: int, subordinate_id: int) -> bool:
    """Как _position_cycle_exists, но обходит ЭФФЕКТИВНОЕ дерево (override
    и то, что из него выведено), а не только явные override-строки —
    иначе пропустим смешанный цикл (A выведен из должностей как начальник
    B, пользователь добавляет override B -> A)."""
    effective = _build_effective_employee_superiors()
    node = superior_id
    seen: set[int] = set()
    while node is not None:
        if node == subordinate_id:
            return True
        if node in seen:
            return False
        seen.add(node)
        node = effective.get(node)
    return False


@transaction.atomic
def add_employee_relation(
    *,
    superior_id: int,
    subordinate_id: int,
    relation_type: RelationType = "direct",
    note: str | None = None,
    created_by: int | None = None,
) -> EmployeeReportingOverride:
    if superior_id == subordinate_id:
        raise EmployeeRelationSelfReferential()

    employees = {
        e.id: e for e in Employee.objects.filter(
            id__in=(superior_id, subordinate_id), is_deleted=False,
        )
    }
    if superior_id not in employees or subordinate_id not in employees:
        raise EmployeeNotFoundForRelation()
    if any(e.status != "active" for e in employees.values()):
        raise EmployeeNotActiveForRelation()

    if EmployeeReportingOverride.objects.filter(
        superior_id=superior_id, subordinate_id=subordinate_id, relation_type=relation_type,
    ).exists():
        raise EmployeeRelationDuplicate()

    if relation_type == "direct":
        current = (
            EmployeeReportingOverride.objects.select_related("superior")
            .filter(subordinate_id=subordinate_id, relation_type="direct")
            .first()
        )
        if current is not None:
            name = f"{current.superior.first_name} {current.superior.last_name}".strip()
            raise EmployeeAlreadyHasSuperior(name, current.id)

    if _employee_cycle_exists(superior_id, subordinate_id):
        raise RelationCycle()

    rel = EmployeeReportingOverride.objects.create(
        superior_id=superior_id,
        subordinate_id=subordinate_id,
        relation_type=relation_type,
        note=note,
        created_by=created_by,
    )
    audit_service.log(
        entity_type="employee_reporting_override",
        entity_id=rel.id,
        action="create",
        new_values={
            "superior_id": str(superior_id), "subordinate_id": str(subordinate_id),
            "relation_type": relation_type,
        },
        changed_by=created_by or 0,
    )
    return rel


def remove_employee_relation(relation_id: int, *, changed_by_id: int | None = None) -> None:
    rel = EmployeeReportingOverride.objects.filter(id=relation_id).first()
    if rel is None:
        raise EmployeeRelationNotFound()
    old_values = {
        "superior_id": str(rel.superior_id), "subordinate_id": str(rel.subordinate_id),
        "relation_type": rel.relation_type,
    }
    rel.delete()
    audit_service.log(
        entity_type="employee_reporting_override",
        entity_id=relation_id,
        action="delete",
        old_values=old_values,
        changed_by=changed_by_id or 0,
    )


# -- руководитель отдела (не порт, закрывает дыру: DepartmentUpdate.manager_id
# нельзя сбросить в null из-за exclude_none-семантики PATCH) -----------------

@transaction.atomic
def set_department_manager(
    department_id: int, employee_id: int | None, *, changed_by_id: int | None = None,
) -> dict:
    dept = Department.objects.filter(id=department_id).first()
    if dept is None:
        raise OrgDepartmentNotFound()

    old_manager_id = dept.manager_id
    if employee_id is None:
        dept.manager = None
    else:
        employee = Employee.objects.filter(id=employee_id, is_deleted=False).first()
        if employee is None:
            raise EmployeeNotFoundForRelation()
        if employee.status != "active":
            raise EmployeeNotActiveForRelation()
        dept.manager_id = employee_id
    dept.save(update_fields=["manager", "updated_at"])

    audit_service.log(
        entity_type="department",
        entity_id=dept.id,
        action="update",
        old_values={"manager_id": str(old_manager_id)},
        new_values={"manager_id": str(employee_id)},
        changed_by=changed_by_id or 0,
    )

    manager = dept.manager if dept.manager_id else None
    return {
        "department_id": dept.id,
        "manager_id": manager.id if manager else None,
        "manager_name": (
            f"{manager.first_name} {manager.last_name}".strip() if manager else None
        ),
        "manager_position_id": manager.position_id if manager else None,
        "manager_avatar_url": manager.avatar_url if manager else None,
    }


# ── subordination matrix ────────────────────────────────────────────────────

def get_subordination_matrix(*, unit_id: int | None = None) -> dict:
    """Матрица связей: superiors (строки), subordinates (столбцы), cells."""
    qs = ReportingRelation.objects.all()
    if unit_id is not None:
        qs = qs.filter(superior_position__department_id=unit_id)
    relations = list(qs)

    superior_ids = list({r.superior_position_id for r in relations})
    subordinate_ids = list({r.subordinate_position_id for r in relations})
    all_ids = list(set(superior_ids + subordinate_ids))

    if not all_ids:
        return {"superiors": [], "subordinates": [], "cells": []}

    pos_map = {p.id: p for p in Position.objects.filter(id__in=all_ids)}

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


# ── org tree (Фича 3) ───────────────────────────────────────────────────────

def _edge(
    source: str,
    target: str,
    relation_type: str,
    *,
    relation_id: int | None = None,
    origin: str,
) -> dict:
    """Единая форма ребра дерева (не порт — добавлено для ручной правки
    оргструктуры).

    relation_id — pk строки БД, по которой связь можно удалить; заполнен
    только когда origin — "employee" (EmployeeReportingOverride) или
    "position" (ReportingRelation), то есть ровно там, где есть что стирать.
    origin — откуда взялась связь: "employee"/"position" — явные данные;
    "department" — явный Department.manager; "inferred" — эвристика
    (choose_department_lead/fallback_parent_pos_id); "structural"/
    "membership"/"employment" — служебные edges дерева отделов, к
    подчинению отношения не имеют.
    """
    return {
        "source": source,
        "target": target,
        "relation_type": relation_type,
        "relation_id": relation_id,
        "origin": origin,
    }


def get_org_tree(
    *,
    root_id: int | None,
    depth: int,
    mode: Literal["positions", "employees", "both"],
    lang: OrgLanguage = "ru",
) -> dict:
    """Строит граф узлов/рёбер для React Flow — буквальный порт с
    аддитивными правками ручной правки оргструктуры:

    * рёбра несут relation_id/origin (см. _edge);
    * dept-узлы с явным Department.manager несут
      meta["manager_source"] = "explicit" (эвристическая ветка по-прежнему
      ставит "inferred" — было и раньше);
    * mode="employees" резолвит рёбра сотрудник->сотрудник через
      EmployeeReportingOverride -> позиционную ReportingRelation -> явный
      Department.manager собственного отдела, и только если ничего не
      нашлось — падает на старый edge от отдела/должности ("employment").
      Эвристика по названию должности (choose_department_lead) и подъём по
      цепочке отделов-предков в резолве РЁБЕР для этого режима не участвуют
      (они — про должности, не про людей); более полный обход с этой
      цепочкой используется только для защиты от циклов при записи, см.
      _build_effective_employee_superiors.

    Намеренно НЕ трогаем: path__startswith без разделителя "." (root "it"
    матчит и "itx"), truthy-проверки if root_id:, недостижимую ветку
    mode == "both" внутри блока mode == "employees" — все три
    задокументированы как дефекты порта в докстринге модуля.
    """
    dept_qs = Department.objects.filter(is_active=True).order_by("path")

    root = None
    if root_id is not None:
        root = Department.objects.filter(id=root_id).first()
        if root is None:
            raise Http404("Root unit not found")
        dept_qs = dept_qs.filter(path__startswith=root.path)

    departments = list(dept_qs)

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
        managers_by_id = {
            m.id: m for m in Employee.objects.filter(
                id__in=manager_ids, status="active", is_deleted=False,
            ).select_related("position")
        }
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
                    "manager_position_title": (
                        manager.position.title if manager and manager.position_id else None
                    ),
                    "manager_source": "explicit" if manager else None,
                },
            }
            nodes.append(dept_node)
            dept_nodes_by_id[dept.id] = dept_node
            parts = dept.path.split(".")
            if len(parts) > 1:
                parent_path = ".".join(parts[:-1])
                parent = next((d for d in departments if d.path == parent_path), None)
                if parent:
                    edges.append(_edge(
                        f"dept_{parent.id}", f"dept_{dept.id}", "structural",
                        origin="structural",
                    ))

    if mode in ("positions", "both"):
        dept_ids = [d.id for d in departments]
        level_colors = {
            threshold.level_number: threshold.color
            for threshold in LevelThreshold.objects.all()
            if threshold.color
        }
        positions = list(
            Position.objects.filter(department_id__in=dept_ids, is_active=True)
            .order_by("level", "weight", "title")
        )
        positions_by_id = {p.id: p for p in positions}
        positions_by_dept: dict[int, list[Position]] = {}
        for pos in positions:
            positions_by_dept.setdefault(pos.department_id, []).append(pos)

        # Active employees occupying these positions, indexed by position_id
        # so the position node can carry holder name(s) without duplicating
        # employees as separate nodes.
        holders_by_pos: dict[int, list[Employee]] = {}
        pos_ids = [p.id for p in positions]
        if positions:
            for emp in Employee.objects.filter(
                position_id__in=pos_ids, status="active", is_deleted=False,
            ):
                holders_by_pos.setdefault(emp.position_id, []).append(emp)

        # Resolve a single reporting parent per position. We pick the first
        # 'direct' relation if present, falling back to any other type.
        superior_by_pos: dict[int, ReportingRelation] = {}
        merged_manager_pos_ids = {
            pos_id
            for pos_id, dept_id in manager_position_to_dept.items()
            if any(p.id == pos_id and p.department_id == dept_id for p in positions)
        }
        visible_pos_ids = set(pos_ids) - merged_manager_pos_ids
        if pos_ids:
            for rel in ReportingRelation.objects.filter(
                subordinate_position_id__in=pos_ids
            ).order_by("id"):
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
                pos for pos in candidates if superior_counts.get(pos.id, 0) > 0
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
        head_pos_id_by_dept: dict[int, int] = {
            dept_id: pos_id
            for pos_id, dept_id in manager_position_to_dept.items()
        }
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
                    "heads_department_id": heads_dept.id if heads_dept else None,
                    "heads_department_name": heads_dept.name if heads_dept else None,
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
                    edges.append(_edge(
                        f"pos_{superior_id}", f"pos_{pos.id}", relation_type,
                        relation_id=rel.id if rel is not None else None,
                        origin="position" if rel is not None else "inferred",
                    ))
                # else: top of the tree — no incoming edge.
            else:  # mode == "both" — keep dept boxes for context
                if rel is not None:
                    manager_dept_id = manager_position_to_dept.get(rel.superior_position_id)
                    if manager_dept_id is not None:
                        edges.append(_edge(
                            f"dept_{manager_dept_id}", f"pos_{pos.id}", rel.relation_type,
                            relation_id=rel.id, origin="position",
                        ))
                    elif rel.superior_position_id in visible_pos_ids:
                        edges.append(_edge(
                            f"pos_{rel.superior_position_id}", f"pos_{pos.id}", rel.relation_type,
                            relation_id=rel.id, origin="position",
                        ))
                    else:
                        edges.append(_edge(
                            f"dept_{pos.department_id}", f"pos_{pos.id}", "membership",
                            origin="membership",
                        ))
                else:
                    edges.append(_edge(
                        f"dept_{pos.department_id}", f"pos_{pos.id}", "membership",
                        origin="membership",
                    ))

    if mode == "employees":
        dept_ids = [d.id for d in departments]
        employees = list(
            Employee.objects.filter(
                department_id__in=dept_ids, status="active", is_deleted=False,
            ).order_by("last_name", "first_name")
        )
        emp_id_set = {e.id for e in employees}
        dept_name_by_id = {d.id: d.name for d in departments}

        emp_position_ids = [e.position_id for e in employees if e.position_id]
        position_title_by_id: dict[int, str] = {}
        if emp_position_ids:
            position_title_by_id = dict(
                Position.objects.filter(id__in=emp_position_ids).values_list("id", "title")
            )

        # Явные персональные связи — приоритетный слой (см. докстринг).
        overrides_by_subordinate: dict[int, list[EmployeeReportingOverride]] = {}
        if employees:
            for row in EmployeeReportingOverride.objects.filter(
                subordinate_id__in=[e.id for e in employees],
            ).order_by("id"):
                overrides_by_subordinate.setdefault(row.subordinate_id, []).append(row)

        # Резолв руководителя должности (direct приоритетнее) — та же
        # логика, что superior_by_pos выше, но вычислена независимо: этот
        # блок достижим и без positions/both в query-параметрах.
        superior_position_of: dict[int, int] = {}
        if emp_position_ids:
            for sub_pos, sup_pos, rel_type in ReportingRelation.objects.filter(
                subordinate_position_id__in=emp_position_ids,
            ).order_by("id").values_list(
                "subordinate_position_id", "superior_position_id", "relation_type",
            ):
                existing = superior_position_of.get(sub_pos)
                if existing is None or rel_type == "direct":
                    superior_position_of[sub_pos] = sup_pos

        # Первый (employees уже отсортирован по last_name/first_name)
        # активный держатель должности.
        holder_of_position: dict[int, int] = {}
        for e in employees:
            if e.position_id:
                holder_of_position.setdefault(e.position_id, e.id)

        dept_manager_of = {d.id: d.manager_id for d in departments if d.manager_id}

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
                    "department_name": dept_name_by_id.get(emp.department_id),
                    "position_id": emp.position_id,
                    "position_title": (
                        position_title_by_id.get(emp.position_id) if emp.position_id else None
                    ),
                },
            })

            rows = overrides_by_subordinate.get(emp.id, [])
            for row in rows:
                if row.superior_id in emp_id_set and row.superior_id != emp.id:
                    edges.append(_edge(
                        f"emp_{row.superior_id}", f"emp_{emp.id}", row.relation_type,
                        relation_id=row.id, origin="employee",
                    ))
            if rows:
                # Явная связь есть — на дефолтный edge от отдела/должности
                # не откатываемся, даже если ни одна строка не прошла фильтр
                # emp_id_set (руководитель вне текущего scope root_id/depth).
                continue

            derived_superior_id: int | None = None
            derived_origin = "department"
            sup_pos = superior_position_of.get(emp.position_id) if emp.position_id else None
            holder = holder_of_position.get(sup_pos) if sup_pos is not None else None
            if holder is not None and holder != emp.id and holder in emp_id_set:
                derived_superior_id = holder
                derived_origin = "position"
            else:
                manager_id = dept_manager_of.get(emp.department_id)
                if manager_id is not None and manager_id != emp.id and manager_id in emp_id_set:
                    derived_superior_id = manager_id
                    derived_origin = "department"

            if derived_superior_id is not None:
                edges.append(_edge(
                    f"emp_{derived_superior_id}", f"emp_{emp.id}", "direct",
                    origin=derived_origin,
                ))
                continue

            # ↓ нетронутый литерал порта (включая недостижимую ветку
            # mode == "both", задокументированную как дефект исходника)
            parent = f"pos_{emp.position_id}" if mode == "both" and emp.position_id else f"dept_{emp.department_id}"
            edges.append(_edge(parent, f"emp_{emp.id}", "employment", origin="employment"))

    tree = {"nodes": nodes, "edges": edges}
    if lang == "en":
        translated = build_translated_org_tree(tree, "en")
        if translated is not None:
            return translated
    return tree


# ── перевод оргдерева (D9) — порт services/hr/app/services/translation_service.py ──

TRANSLATABLE_META_FIELDS = (
    "department_name",
    "heads_department_name",
    "manager_position_title",
)


def _collect_tree_texts(tree: dict) -> tuple[list[str], list[tuple[str, int, str | None]]]:
    texts: list[str] = []
    refs: list[tuple[str, int, str | None]] = []

    for idx, node in enumerate(tree.get("nodes") or []):
        label = node.get("label")
        if isinstance(label, str) and label.strip():
            refs.append(("node", idx, None))
            texts.append(label)

        meta = node.get("meta")
        if not isinstance(meta, dict):
            continue
        for key in TRANSLATABLE_META_FIELDS:
            value = meta.get(key)
            if isinstance(value, str) and value.strip():
                refs.append(("meta", idx, key))
                texts.append(value)

    return texts, refs


def _apply_tree_texts(
    tree: dict,
    refs: list[tuple[str, int, str | None]],
    translated: list[str],
) -> dict:
    result = copy.deepcopy(tree)
    nodes = result.get("nodes") or []
    for ref, value in zip(refs, translated):
        kind, idx, key = ref
        if idx >= len(nodes):
            continue
        if kind == "node":
            nodes[idx]["label"] = value
            continue
        meta = nodes[idx].get("meta")
        if isinstance(meta, dict) and key:
            meta[key] = value
    return result


def _translate_with_google(texts: list[str], target_lang: OrgLanguage) -> list[str] | None:
    api_key = getattr(settings, "GOOGLE_TRANSLATE_API_KEY", "").strip()
    if not api_key:
        return None

    base = getattr(
        settings, "GOOGLE_TRANSLATE_API_BASE",
        "https://translation.googleapis.com/language/translate/v2",
    )
    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.post(
                base,
                params={"key": api_key},
                json={"q": texts, "source": "ru", "target": target_lang, "format": "text"},
            )
            response.raise_for_status()
    except httpx.HTTPError as exc:
        logger.warning("org_tree_google_translation_failed target_lang=%s error=%s", target_lang, exc)
        return None

    rows = response.json().get("data", {}).get("translations", [])
    translated = [
        html.unescape(row.get("translatedText", ""))
        for row in rows
        if isinstance(row, dict)
    ]
    return translated if len(translated) == len(texts) else None


def _parse_libre_translated_text(payload: dict, expected_count: int) -> list[str] | None:
    value = payload.get("translatedText")
    if isinstance(value, list):
        translated = [html.unescape(str(item)) for item in value]
        return translated if len(translated) == expected_count else None
    if isinstance(value, str) and expected_count == 1:
        return [html.unescape(value)]
    return None


def _translate_with_libretranslate(texts: list[str], target_lang: OrgLanguage) -> list[str] | None:
    base_url = getattr(settings, "LIBRE_TRANSLATE_API_URL", "").strip().rstrip("/")
    if not base_url:
        return None

    api_key = getattr(settings, "LIBRE_TRANSLATE_API_KEY", "").strip()

    def payload(q: str | list[str]) -> dict:
        body = {"q": q, "source": "ru", "target": target_lang, "format": "text"}
        if api_key:
            body["api_key"] = api_key
        return body

    try:
        with httpx.Client(timeout=20.0) as client:
            try:
                batch_response = client.post(f"{base_url}/translate", json=payload(texts))
                batch_response.raise_for_status()
                batch = _parse_libre_translated_text(batch_response.json(), len(texts))
                if batch is not None:
                    return batch
            except (httpx.HTTPError, ValueError) as exc:
                logger.info("org_tree_libretranslate_batch_failed target_lang=%s error=%s", target_lang, exc)

            translated: list[str] = []
            for text in texts:
                response = client.post(f"{base_url}/translate", json=payload(text))
                response.raise_for_status()
                row = _parse_libre_translated_text(response.json(), 1)
                if row is None:
                    return None
                translated.extend(row)
            return translated
    except httpx.HTTPError as exc:
        logger.warning("org_tree_libretranslate_failed target_lang=%s error=%s", target_lang, exc)
        return None


def build_translated_org_tree(tree: dict, target_lang: OrgLanguage) -> dict | None:
    """Return translated copy of an org tree, or None when unavailable."""
    if target_lang == "ru":
        return copy.deepcopy(tree)
    if target_lang != "en":
        return None

    texts, refs = _collect_tree_texts(tree)
    if not texts:
        return copy.deepcopy(tree)

    translated = (
        _translate_with_google(texts, target_lang)
        or _translate_with_libretranslate(texts, target_lang)
    )
    if translated is None:
        return None

    if len(translated) != len(texts):
        logger.warning(
            "org_tree_translation_incomplete expected=%d received=%d",
            len(texts), len(translated),
        )
        return None

    return _apply_tree_texts(tree, refs, translated)
