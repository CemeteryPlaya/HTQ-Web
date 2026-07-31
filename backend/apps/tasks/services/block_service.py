"""Блоки объекта и объёмы работ на них.

Новый домен — FastAPI-оригинала у него нет, как и у ``site_service``.

Здесь живёт единственная в аппе арифметика выполнения «по штукам».
Остальной код меряет прогресс статусами задач (``project_service.progress``,
``gantt_service._PROGRESS``), и для разнокалиберных задач это единственное,
что можно посчитать. У блока же есть плановый объём, а у его задач —
фактический, поэтому здесь процент означает буквально «развезли 180 валов
из 250», а не «две задачи из трёх в статусе done».

Правило «блок задачи принадлежит объекту задачи» намеренно НЕ здесь, а в
``site_service.resolve_task_block`` — рядом с близнецом про объект, чтобы
оба правила валидации задачи читались в одном месте.
"""

from __future__ import annotations

from decimal import Decimal

from django.db import transaction
from django.http import Http404

from ..models import (SiteBlock, SiteBlockVolume, Task, WorkVolumeType)
from . import daily_report_service


def list_blocks(site_id: int, *, status: str | None = None) -> list[SiteBlock]:
    qs = SiteBlock.objects.filter(site_id=site_id)
    if status:
        qs = qs.filter(status=status)
    return list(qs.order_by("order", "name"))


def get_block(block_id: int) -> SiteBlock:
    block = SiteBlock.objects.filter(pk=block_id).first()
    if block is None:
        raise Http404("Block not found")
    return block


def create_block(site_id: int, payload: dict) -> SiteBlock:
    return SiteBlock.objects.create(site_id=site_id, **payload)


def update_block(block_id: int, changes: dict) -> SiteBlock:
    block = get_block(block_id)
    for field, value in changes.items():
        setattr(block, field, value)
    block.save()
    return block


class BlockInUse(Exception):
    """Блок нельзя удалить: на него ссылаются задачи.

    ``Task.site_block`` — ``SET_NULL``, то есть удаление молча обнулило бы
    задачам блок и испортило отчётность задним числом. Та же логика и тот
    же выход, что у ``site_service.SiteInUse``: статус ``done``/``suspended``
    вместо удаления.
    """

    def __init__(self, tasks: int):
        self.tasks = tasks
        super().__init__(
            f"Блок используется: задач — {tasks}. "
            f"Переведите его в статус «сдан» вместо удаления."
        )


def delete_block(block_id: int) -> None:
    block = get_block(block_id)
    tasks = Task.objects.filter(site_block_id=block_id, is_deleted=False).count()
    if tasks:
        raise BlockInUse(tasks)
    block.delete()


# ── объёмы блока ────────────────────────────────────────────────────────

def require_volume_types(type_ids) -> None:
    """Проверить, что все виды объёмов существуют.

    Явная проверка, а не расчёт на FK: нарушение внешнего ключа PostgreSQL
    поднимает не на ``INSERT``, а на коммите транзакции, так что перехват
    ``IntegrityError`` вокруг записи молча не срабатывает — запрос отвечает
    200, а падает уже за пределами вьюхи. Здесь же получается честный 422 с
    именем проблемы.
    """
    wanted = set(type_ids)
    if not wanted:
        return
    known = set(WorkVolumeType.objects.filter(pk__in=wanted)
                .values_list("id", flat=True))
    missing = sorted(wanted - known)
    if missing:
        raise ValueError(f"Виды объёма работ не найдены: {missing}")


@transaction.atomic
def set_block_volumes(block_id: int, volumes: list[dict]) -> list[SiteBlockVolume]:
    """Заменить набор плановых объёмов блока целиком.

    Замена, а не инкремент — по той же причине, что у
    ``site_service.set_project_sites``: форма присылает полный список, и
    инкрементальный API заставил бы её считать разницу.
    """
    get_block(block_id)                      # 404 раньше любых записей
    wanted = {v["volume_type_id"]: v["planned_quantity"] for v in volumes}
    require_volume_types(wanted)

    SiteBlockVolume.objects.filter(block_id=block_id).exclude(
        volume_type_id__in=wanted).delete()
    for type_id, quantity in wanted.items():
        SiteBlockVolume.objects.update_or_create(
            block_id=block_id, volume_type_id=type_id,
            defaults={"planned_quantity": quantity},
        )
    return list_block_volumes(block_id)


def list_block_volumes(block_id: int) -> list[SiteBlockVolume]:
    return list(SiteBlockVolume.objects.filter(block_id=block_id)
                .select_related("volume_type")
                .order_by("volume_type__name"))


# ── прогресс по объёмам ─────────────────────────────────────────────────

def block_progress(block_id: int) -> dict:
    """Выполнение блока в штуках: план с блока, факт — сумма по его задачам.

    Возвращает разбивку по видам работ плюс агрегат ``percent``. Агрегат
    считается как отношение сумм ОТНОШЕНИЙ по каждому виду, а не как
    (сумма факта / сумма плана): складывать 250 валов и 40 тонн металла в
    одно число нельзя — единицы разные. Каждый вид даёт свой процент, а
    итог — их среднее, то есть «в среднем по видам работ блок готов на N%».

    Виды работ, у которых план нулевой, в среднее не входят: делить на ноль
    нечем, а считать такой вид выполненным на 100% значило бы завышать итог.
    """
    planned = {row.volume_type_id: row
               for row in list_block_volumes(block_id)}
    # Факт — из ежедневных отчётов, а не из колонки на строке объёма:
    # у отчёта есть дата выполнения, и «сколько сделано» можно спросить на
    # любой день, а не только «сейчас» (см. daily_report_service).
    done: dict[int, Decimal] = {}
    by_task_and_type = daily_report_service.completed_by_volume_type(
        block_id=block_id)
    for (_task_id, type_id), total in by_task_and_type.items():
        done[type_id] = done.get(type_id, Decimal("0")) + total

    items, ratios = [], []
    for type_id, row in planned.items():
        completed = done.get(type_id) or Decimal("0")
        plan = row.planned_quantity
        percent = float(completed / plan * 100) if plan > 0 else None
        if percent is not None:
            ratios.append(min(percent, 100.0))
        items.append({
            "volume_type_id": type_id,
            "volume_type_name": row.volume_type.name,
            "unit": str(row.volume_type.unit),
            "planned_quantity": float(plan),
            "completed_quantity": float(completed),
            "percent": round(percent, 1) if percent is not None else None,
        })

    return {
        "block_id": block_id,
        "items": items,
        # None, а не 0: «объёмы не заданы» и «не сделано ничего» — разные
        # состояния, и рисовать пустой блок как 0% значило бы врать.
        "percent": round(sum(ratios) / len(ratios), 1) if ratios else None,
    }


# ── ответы ──────────────────────────────────────────────────────────────

def build_volume(row: SiteBlockVolume) -> dict:
    return {
        "id": row.id,
        "volume_type_id": row.volume_type_id,
        "volume_type_name": row.volume_type.name,
        "unit": str(row.volume_type.unit),
        "planned_quantity": float(row.planned_quantity),
    }


def build_block(block: SiteBlock, *, volumes: list[SiteBlockVolume] | None = None
                ) -> dict:
    return {
        "id": block.id,
        "site_id": block.site_id,
        "name": block.name,
        "code": block.code,
        "order": block.order,
        "status": str(block.status),
        "start_date": str(block.start_date) if block.start_date else None,
        "end_date": str(block.end_date) if block.end_date else None,
        "volumes": [build_volume(v) for v in (volumes or [])],
        "created_at": str(block.created_at),
        "updated_at": str(block.updated_at),
    }


def build_blocks(blocks: list[SiteBlock]) -> list[dict]:
    """Список блоков с их объёмами — одним дополнительным запросом.

    Не ``build_block`` в цикле: тот сходил бы за объёмами на каждый блок,
    а блоков на площадке десятки.
    """
    by_block: dict[int, list[SiteBlockVolume]] = {}
    for row in (SiteBlockVolume.objects
                .filter(block__in=blocks)
                .select_related("volume_type")
                .order_by("volume_type__name")):
        by_block.setdefault(row.block_id, []).append(row)
    return [build_block(b, volumes=by_block.get(b.id, [])) for b in blocks]


__all__ = [
    "BlockInUse",
    "list_blocks", "get_block", "create_block", "update_block", "delete_block",
    "set_block_volumes", "list_block_volumes", "block_progress",
    "require_volume_types",
    "build_block", "build_blocks", "build_volume",
]
