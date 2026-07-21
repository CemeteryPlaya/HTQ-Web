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
from django.http import Http404

from apps.hr.models import Department, Employee, LevelThreshold, OrgSettings, Position, ReportingRelation

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
    exists = ReportingRelation.objects.filter(
        superior_position_id=superior_id,
        subordinate_position_id=subordinate_id,
        relation_type=relation_type,
    ).exists()
    if exists:
        raise RelationDuplicate()
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

def get_org_tree(
    *,
    root_id: int | None,
    depth: int,
    mode: Literal["positions", "employees", "both"],
    lang: OrgLanguage = "ru",
) -> dict:
    """Строит граф узлов/рёбер для React Flow — буквальный порт."""
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
            )
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
                },
            }
            nodes.append(dept_node)
            dept_nodes_by_id[dept.id] = dept_node
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
            for rel in ReportingRelation.objects.filter(subordinate_position_id__in=pos_ids):
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
        employees = list(
            Employee.objects.filter(
                department_id__in=dept_ids, status="active", is_deleted=False,
            ).order_by("last_name", "first_name")
        )
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
