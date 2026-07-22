"""Бизнес-логика должностей — порт services/hr/app/services/position_service.py
(+ repositories/base_repo.py в части, которую он использовал).

Весовая система (решения из плана, docs/plans/2026-07-20-hr-domain.md):

* ``weight`` — глобально уникален (реальный UNIQUE на колонке); ``level`` —
  кэш, пересчитываемый из ``hr_levelthreshold`` при каждой смене веса
  (``update_weight``, ``update_position`` с полем weight) и при изменении
  порога (``update_threshold``/``create_threshold``/``delete_threshold``
  пересчитывают ВСЕ должности, не только затронутый диапазон — это
  БУКВАЛЬНОЕ поведение исходника: ``_recompute_levels_in_range`` там
  определён, но НИКОГДА не вызывается ни одним эндпойнтом — мёртвый код;
  порт его не переносит, а ``_recompute_all_levels`` зовётся везде).
* ``move``/``rebalance`` сначала пробуют локальный пересчёт веса
  (``_apply_new_weight``), а при конфликте/выходе за диапазон порога —
  делают полный ребаланс уровня через двухфазную схему (все веса сначала
  уводятся во временный отрицательный диапазон, потом расставляются
  финально) — иначе временная коллизия упёрлась бы в реальный UNIQUE.
* Каждая мутация — ``@transaction.atomic``: исходник коммитит один раз в
  конце запроса (FastAPI session-per-request), поэтому частичная запись при
  ошибке посередине (например 409 при ребалансе) должна откатываться
  целиком, а не оставлять половину должностей уже переставленными.
"""
from __future__ import annotations

from django.db import transaction
from django.http import Http404

from apps.hr.models import LevelThreshold, Position, PositionWeightAudit

_DEFAULT_LEVEL = 5  # fallback, если вес выходит за все настроенные пороги


# ── исключения (структурированные — carries .detail, статус решает вьюха) ───

class WeightTaken(Exception):
    """409: конфликт по глобально уникальному весу."""

    def __init__(self, weight: int, existing: Position) -> None:
        self.detail = (
            f"Weight {weight} is already taken by position '{existing.title}' "
            f"(id={existing.id}). Choose a different weight or update the "
            "existing position first."
        )
        super().__init__(self.detail)


class WeightInvalid(Exception):
    """422: отрицательный вес."""

    def __init__(self, detail: str = "weight must be >= 0") -> None:
        self.detail = detail
        super().__init__(detail)


class SystemPositionFieldsLocked(Exception):
    """409: попытка поменять title/department_id/is_active у системной должности."""

    def __init__(self, blocked: set[str]) -> None:
        self.detail = (
            "Системную должность нельзя редактировать в этих полях: "
            + ", ".join(sorted(blocked))
        )
        super().__init__(self.detail)


class SystemPositionProtected(Exception):
    """409: попытка удалить системную должность."""

    detail = "Системную должность нельзя удалить"

    def __init__(self) -> None:
        super().__init__(self.detail)


class ThresholdRangeInvalid(Exception):
    """422: weight_from > weight_to."""

    detail = "weight_from must be <= weight_to"

    def __init__(self) -> None:
        super().__init__(self.detail)


class ThresholdRangeOverlap(Exception):
    """409: диапазон пересекается с другим порогом."""

    def __init__(self, existing: LevelThreshold) -> None:
        self.detail = (
            "Level threshold range overlaps with "
            f"L{existing.level_number} ({existing.weight_from}-{existing.weight_to})"
        )
        super().__init__(self.detail)


class ThresholdExists(Exception):
    """409: level_number уже занят."""

    def __init__(self, level_number: int) -> None:
        self.detail = f"Level threshold {level_number} already exists"
        super().__init__(self.detail)


class MoveValidationError(Exception):
    """422: некорректные параметры move (сам на себя / before==after)."""

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(detail)


# ── сериализаторы (формы из schemas/position.py) ─────────────────────────────

def _serialize_permissions(raw: dict | None) -> dict | None:
    if raw is None:
        return None
    return {"hr_level": raw.get("hr_level"), "permissions": list(raw.get("permissions") or [])}


def serialize(pos: Position) -> dict:
    """PositionOut."""
    return {
        "id": pos.id,
        "title": pos.title,
        "department_id": pos.department_id,
        "grade": pos.grade,
        "description": pos.description,
        "requirements": pos.requirements,
        "is_active": pos.is_active,
        "weight": pos.weight,
        "permissions": _serialize_permissions(pos.permissions),
        "level": pos.level,
        "is_system": pos.is_system,
        "created_at": pos.created_at.isoformat(),
        "updated_at": pos.updated_at.isoformat(),
    }


def serialize_threshold(t: LevelThreshold) -> dict:
    """LevelThresholdOut."""
    return {
        "id": t.id,
        "level_number": t.level_number,
        "weight_from": t.weight_from,
        "weight_to": t.weight_to,
        "label": t.label,
        "color": t.color,
        "created_at": t.created_at.isoformat(),
        "updated_at": t.updated_at.isoformat(),
    }


def paginate(items: list[dict], *, total: int, page: int, limit: int) -> dict:
    """PaginatedResponse envelope — форма ТОЧНО как schemas/common.py."""
    pages = (total + limit - 1) // limit
    return {"items": items, "total": total, "page": page, "pages": pages, "limit": limit}


# ── вычисление уровня ─────────────────────────────────────────────────────────

def _compute_level(weight: int) -> int:
    threshold = (
        LevelThreshold.objects.filter(weight_from__lte=weight, weight_to__gte=weight).first()
    )
    return threshold.level_number if threshold else _DEFAULT_LEVEL


def _get_threshold(level_number: int) -> LevelThreshold | None:
    return LevelThreshold.objects.filter(level_number=level_number).first()


def _assert_weight_free(weight: int, exclude_id: int | None = None) -> None:
    qs = Position.objects.filter(weight=weight)
    if exclude_id:
        qs = qs.exclude(id=exclude_id)
    existing = qs.first()
    if existing:
        raise WeightTaken(weight, existing)


def _assert_threshold_range_free(*, level_number: int, weight_from: int, weight_to: int) -> None:
    if weight_from > weight_to:
        raise ThresholdRangeInvalid()

    existing = (
        LevelThreshold.objects.exclude(level_number=level_number)
        .filter(weight_from__lte=weight_to, weight_to__gte=weight_from)
        .first()
    )
    if existing:
        raise ThresholdRangeOverlap(existing)


def _record_weight_audit(
    *, position_id: int, old_weight: int | None, new_weight: int | None,
    old_level: int | None, new_level: int | None, reason: str, actor_user_id: int | None,
) -> None:
    PositionWeightAudit.objects.create(
        position_id=position_id, old_weight=old_weight, new_weight=new_weight,
        old_level=old_level, new_level=new_level, changed_by=actor_user_id, reason=reason,
    )


def _apply_new_weight(
    pos: Position, new_weight: int, *, reason: str, actor_user_id: int | None = None,
) -> Position:
    if new_weight < 0:
        raise WeightInvalid()

    _assert_weight_free(new_weight, exclude_id=pos.id)
    new_level = _compute_level(new_weight)
    old_weight = pos.weight
    old_level = pos.level
    if old_weight == new_weight and old_level == new_level:
        return pos

    pos.weight = new_weight
    pos.level = new_level
    pos.save()
    _record_weight_audit(
        position_id=pos.id, old_weight=old_weight, new_weight=new_weight,
        old_level=old_level, new_level=new_level, reason=reason, actor_user_id=actor_user_id,
    )
    return pos


# ── CRUD ───────────────────────────────────────────────────────────────────

def list_positions(*, page: int = 1, limit: int = 20) -> tuple[list[Position], int]:
    offset = (page - 1) * limit
    qs = Position.objects.order_by("weight")
    total = qs.count()
    items = list(qs[offset:offset + limit])
    return items, total


def get_position(id: int) -> Position:
    pos = Position.objects.filter(id=id).first()
    if pos is None:
        raise Http404("Position not found")
    return pos


@transaction.atomic
def create_position(data) -> Position:
    _assert_weight_free(data.weight)
    level = _compute_level(data.weight)
    payload = data.model_dump()
    payload["level"] = level
    # Всё созданное через API по определению не системное; is_system=True
    # ставит только alembic-бэкфилл 013 (сюда он не переносится).
    payload["is_system"] = False
    pos = Position.objects.create(**payload)
    return pos


@transaction.atomic
def update_position(id: int, data, *, actor_user_id: int | None = None) -> Position:
    pos = get_position(id)
    patch = data.model_dump(exclude_none=True)
    next_weight = patch.pop("weight", None)

    if pos.is_system:
        # Системные должности — часть базового оргчарта. Переименование /
        # смена отдела / деактивация запрещены (сломали бы ссылки и
        # эвристику авторизации); вес, грейд, описание, требования и
        # матрица прав остаются редактируемыми.
        blocked = {"title", "department_id", "is_active"} & patch.keys()
        if blocked:
            raise SystemPositionFieldsLocked(blocked)

    if patch:
        for field, value in patch.items():
            setattr(pos, field, value)
        pos.save()
    if next_weight is not None:
        pos = _apply_new_weight(pos, next_weight, reason="manual", actor_user_id=actor_user_id)
    return pos


@transaction.atomic
def delete_position(id: int) -> None:
    pos = get_position(id)
    if pos.is_system:
        raise SystemPositionProtected()
    pos.delete()


# ── вес ────────────────────────────────────────────────────────────────────

@transaction.atomic
def update_weight(
    id: int, weight: int, *, actor_user_id: int | None = None, reason: str = "manual",
) -> Position:
    pos = get_position(id)
    return _apply_new_weight(pos, weight, reason=reason, actor_user_id=actor_user_id)


def _get_position_for_move(position_id: int | None) -> Position | None:
    if position_id is None:
        return None
    pos = Position.objects.select_for_update().filter(id=position_id).first()
    if pos is None:
        raise Http404(f"Position {position_id} not found")
    return pos


def _weight_between(before: Position | None, after: Position | None) -> int | None:
    if before and after:
        if before.weight >= after.weight:
            before, after = after, before
        if after.weight - before.weight < 2:
            return None
        return (before.weight + after.weight) // 2
    if before:
        return before.weight + 100
    if after:
        return after.weight - 100
    return None


@transaction.atomic
def move_position(
    position_id: int, *, before_position_id: int | None = None,
    after_position_id: int | None = None, target_level: int | None = None,
    actor_user_id: int | None = None,
) -> Position:
    if before_position_id and before_position_id == after_position_id:
        raise MoveValidationError("before_position_id and after_position_id must differ")
    if position_id in (before_position_id, after_position_id):
        raise MoveValidationError("position cannot be moved relative to itself")

    pos = Position.objects.select_for_update().filter(id=position_id).first()
    if pos is None:
        raise Http404("Position not found")

    before = _get_position_for_move(before_position_id)
    after = _get_position_for_move(after_position_id)
    effective_level = target_level or (before.level if before else after.level if after else pos.level)

    if target_level is not None and not _get_threshold(target_level):
        raise Http404("Target level not found")

    new_weight = _weight_between(before, after)
    threshold = _get_threshold(effective_level)
    if (
        new_weight is None
        or new_weight < 0
        or (threshold and not (threshold.weight_from <= new_weight <= threshold.weight_to))
    ):
        return _rebalance_insert(
            pos, target_level=effective_level, before_position_id=before_position_id,
            after_position_id=after_position_id, actor_user_id=actor_user_id,
        )

    try:
        return _apply_new_weight(pos, new_weight, reason="move", actor_user_id=actor_user_id)
    except WeightTaken:
        return _rebalance_insert(
            pos, target_level=effective_level, before_position_id=before_position_id,
            after_position_id=after_position_id, actor_user_id=actor_user_id,
        )


def _rebalance_insert(
    pos: Position, *, target_level: int, before_position_id: int | None,
    after_position_id: int | None, actor_user_id: int | None,
) -> Position:
    positions = _positions_for_level(target_level, lock=True)
    ordered = [p for p in positions if p.id != pos.id]

    insert_at = len(ordered)
    if before_position_id is not None:
        insert_at = next(
            (i + 1 for i, item in enumerate(ordered) if item.id == before_position_id),
            insert_at,
        )
    elif after_position_id is not None:
        insert_at = next(
            (i for i, item in enumerate(ordered) if item.id == after_position_id),
            0,
        )

    ordered.insert(insert_at, pos)
    _rebalance_positions(ordered, level=target_level, reason="move", actor_user_id=actor_user_id)
    pos.refresh_from_db()
    return pos


# ── ребаланс ───────────────────────────────────────────────────────────────

@transaction.atomic
def rebalance_level(level: int, *, actor_user_id: int | None = None, reason: str = "rebalance") -> int:
    if not _get_threshold(level):
        raise Http404("Level threshold not found")
    positions = _positions_for_level(level, lock=True)
    _rebalance_positions(positions, level=level, reason=reason, actor_user_id=actor_user_id)
    return len(positions)


@transaction.atomic
def rebalance_all(*, actor_user_id: int | None = None) -> dict[int, int]:
    positions = list(
        Position.objects.order_by("level", "weight", "title", "id").select_for_update()
    )
    counts: dict[int, int] = {}
    for pos in positions:
        counts[pos.level] = counts.get(pos.level, 0) + 1
    _rebalance_positions(positions, level=None, reason="rebalance", actor_user_id=actor_user_id)
    return counts


def _positions_for_level(level: int, *, lock: bool) -> list[Position]:
    qs = Position.objects.filter(level=level).order_by("weight", "title", "id")
    if lock:
        qs = qs.select_for_update()
    return list(qs)


def _final_weights(positions: list[Position], level: int | None) -> list[int]:
    if not positions:
        return []
    if level is None:
        return [idx * 100 for idx in range(len(positions))]

    threshold = _get_threshold(level)
    if not threshold:
        return [idx * 100 for idx in range(len(positions))]

    max_sparse = threshold.weight_from + ((len(positions) - 1) * 100)
    if max_sparse <= threshold.weight_to:
        return [threshold.weight_from + (idx * 100) for idx in range(len(positions))]

    width = threshold.weight_to - threshold.weight_from
    if len(positions) <= width + 1:
        step = max(1, width // max(len(positions) - 1, 1))
        return [threshold.weight_from + (idx * step) for idx in range(len(positions))]

    # Настроенный диапазон не может вместить все должности с уникальными
    # весами. Сохраняем детерминированный порядок, кэш-уровень следует за
    # итоговым весом (может отличаться от заявленного level порога).
    return [threshold.weight_from + idx for idx in range(len(positions))]


def _rebalance_positions(
    positions: list[Position], *, level: int | None, reason: str, actor_user_id: int | None,
) -> None:
    if not positions:
        return

    old_values = {pos.id: (pos.weight, pos.level) for pos in positions}
    final_weights = _final_weights(positions, level)

    # Двухфазно: сначала все веса уводим во временный отрицательный
    # диапазон (не пересекается с реальными весами — UNIQUE не срабатывает),
    # потом расставляем финальные один за другим.
    temp_base = -1_000_000_000
    for idx, pos in enumerate(positions):
        pos.weight = temp_base - idx
        pos.save()

    for pos, final_weight in zip(positions, final_weights, strict=True):
        _assert_weight_free(final_weight, exclude_id=pos.id)
        old_weight, old_level = old_values[pos.id]
        new_level = _compute_level(final_weight)
        pos.weight = final_weight
        pos.level = new_level
        pos.save()
        if old_weight != final_weight or old_level != new_level:
            _record_weight_audit(
                position_id=pos.id, old_weight=old_weight, new_weight=final_weight,
                old_level=old_level, new_level=new_level, reason=reason, actor_user_id=actor_user_id,
            )


# ── пороги уровней ────────────────────────────────────────────────────────

def list_thresholds() -> list[LevelThreshold]:
    return list(LevelThreshold.objects.order_by("level_number")[:100])


@transaction.atomic
def create_threshold(data, *, actor_user_id: int | None = None) -> LevelThreshold:
    if _get_threshold(data.level_number):
        raise ThresholdExists(data.level_number)
    _assert_threshold_range_free(
        level_number=data.level_number, weight_from=data.weight_from, weight_to=data.weight_to,
    )
    threshold = LevelThreshold.objects.create(**data.model_dump())
    _recompute_all_levels(actor_user_id=actor_user_id)
    threshold.refresh_from_db()
    return threshold


@transaction.atomic
def update_threshold(level_number: int, data, *, actor_user_id: int | None = None) -> LevelThreshold:
    threshold = _get_threshold(level_number)
    if not threshold:
        raise Http404(f"Level threshold {level_number} not found")

    patch = data.model_dump(exclude_unset=True)
    next_weight_from = patch.get("weight_from", threshold.weight_from)
    next_weight_to = patch.get("weight_to", threshold.weight_to)
    _assert_threshold_range_free(
        level_number=level_number, weight_from=next_weight_from, weight_to=next_weight_to,
    )

    for key, value in patch.items():
        setattr(threshold, key, value)
    threshold.save()
    _recompute_all_levels(actor_user_id=actor_user_id)
    threshold.refresh_from_db()
    return threshold


@transaction.atomic
def delete_threshold(level_number: int, *, actor_user_id: int | None = None) -> None:
    threshold = _get_threshold(level_number)
    if not threshold:
        raise Http404(f"Level threshold {level_number} not found")
    threshold.delete()
    _recompute_all_levels(actor_user_id=actor_user_id)


def _recompute_all_levels(*, actor_user_id: int | None) -> int:
    """Пересчитывает level ВСЕХ должностей — буквальное поведение исходника
    (``_recompute_levels_in_range`` там не мёртв по коду, но мёртв по
    вызовам: ни один эндпойнт его не использует)."""
    positions = list(Position.objects.order_by("id").select_for_update())
    changed = 0
    for pos in positions:
        old_level = pos.level
        new_level = _compute_level(pos.weight)
        if new_level != old_level:
            pos.level = new_level
            pos.save()
            _record_weight_audit(
                position_id=pos.id, old_weight=pos.weight, new_weight=pos.weight,
                old_level=old_level, new_level=new_level, reason="threshold_change",
                actor_user_id=actor_user_id,
            )
            changed += 1
    return changed
