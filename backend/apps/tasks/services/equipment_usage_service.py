"""Учёт задействования техники: что занято на дату D и когда чем работали.

Новый домен, FastAPI-оригинала нет.

Отвечает на два вопроса из спеки (§10 п.2), которые до сих пор задать было
нечем: «какая техника и в каком количестве задействована СЕЙЧАС на задаче /
роудмапе / блоке / площадке / проекте» и «сколько времени и на каких задачах
использовалась категория».

**Отдельной таблицы под это НЕТ, и это осознанно.** SPEC §3.1 предлагает
завести ``EquipmentEngagement`` (категория, количество, период, XOR
роудмап/задача) — но это поле в поле уже существующий
``ResourceRequirement(kind=equipment)``. Заводить вторую таблицу с тем же
смыслом значило бы получить два расходящихся ответа на один вопрос; здесь
пишутся только недостающие ЗАПРОСЫ над тем, что есть.

Два слоя, которые дополняют друг друга и потому считаются отдельно:

* ``ResourceRequirement`` — план ТИПОМ И КОЛИЧЕСТВОМ: «нужны 2 кары».
  Отвечает на «сколько техники должно быть занято».
* ``ResourceAllocation`` — факт КОНКРЕТНОЙ машиной: «кара K-1». Отвечает на
  «какие именно машины заняты» и даёт историю по инвентарным номерам.

Период, в который строка «занята», нигде не хранится целиком: у потребности
он свой (``start_date``/``end_date``), у именного назначения его нет вовсе, и
оно наследует срок своей цели — задачи или роудмапа. Разрешение этой цепочки
и есть основная работа модуля.
"""

from __future__ import annotations

import datetime as dt

from django.db.models import Count, Q, Sum
from django.db.models.functions import Coalesce

from ..models import ResourceAllocation, ResourceKind, ResourceRequirement


def _scope_q(prefix: str, *, project_id=None, site_id=None, block_id=None,
             roadmap_id=None, task_id=None) -> Q:
    """Условие «строка относится к выбранному узлу иерархии».

    ``prefix`` — путь до задачи/роудмапа от таблицы, по которой фильтруем
    (у потребностей и назначений он одинаковый, отсюда параметр).

    Узел задаётся ОДНИМ из аргументов, но перебираются оба пути — через
    задачу и через роудмап: техника бывает занята и напрямую на пакете, и
    на его задачах, и обе занятости настоящие.
    """
    if task_id is not None:
        return Q(**{f"{prefix}task_id": task_id})
    if roadmap_id is not None:
        return (Q(**{f"{prefix}roadmap_id": roadmap_id})
                | Q(**{f"{prefix}task__roadmap_id": roadmap_id}))
    if block_id is not None:
        return (Q(**{f"{prefix}roadmap__site_block_id": block_id})
                | Q(**{f"{prefix}task__site_block_id": block_id}))
    if site_id is not None:
        return (Q(**{f"{prefix}roadmap__site_block__site_id": site_id})
                | Q(**{f"{prefix}task__site_id": site_id}))
    if project_id is not None:
        return (Q(**{f"{prefix}roadmap__project_id": project_id})
                | Q(**{f"{prefix}task__project_id": project_id}))
    return Q()


# Границы «занятости» строки. Coalesce-лесенка повторяет приём из
# ``gantt_service.resource_gantt``: строка с одной заполненной датой это
# отрезок нулевой длины на эту дату, а не «всегда» и не «никогда».
_REQ_START = Coalesce("start_date", "end_date",
                      "roadmap__planned_start_date", "task__start_date",
                      "task__due_date")
_REQ_END = Coalesce("end_date", "start_date",
                    "roadmap__planned_end_date", "task__due_date",
                    "task__start_date")
# У назначения своих дат нет: оно занято ровно столько, сколько идёт его
# цель. Сначала период потребности, которую оно закрывает, потом сроки
# задачи, потом плановые сроки пакета.
_ALLOC_START = Coalesce("requirement__start_date", "task__start_date",
                        "task__due_date", "roadmap__planned_start_date")
_ALLOC_END = Coalesce("requirement__end_date", "task__due_date",
                      "task__start_date", "roadmap__planned_end_date")


def _overlapping(qs, start_expr, end_expr, date_from: dt.date,
                 date_to: dt.date):
    """Строки, чей период пересекается с окном.

    Строки без единой даты отбрасываются: у них нет периода, и включать их
    «на всякий случай» значило бы показывать технику занятой всегда.
    """
    return (qs.annotate(eff_start=start_expr, eff_end=end_expr)
            .filter(eff_start__isnull=False, eff_end__isnull=False)
            .filter(eff_start__lte=date_to, eff_end__gte=date_from))


def engaged_on(target_date: dt.date, **scope) -> list[dict]:
    """Что задействовано на дату D, свёрнутое по категориям техники.

    Одна дата, а не окно: вопрос «что занято сегодня» — точечный, и
    окно с равными границами выражает его без отдельного кода.

    По каждой категории отдаётся и план (``planned`` — сумма количеств
    потребностей), и факт (``assigned`` — число конкретных машин). Обе
    цифры рядом, потому что «нужно 2 кары, выделена 1» — это и есть
    рабочий ответ; одна из них по отдельности вводит в заблуждение.
    """
    scope_q = _scope_q("", **scope)

    planned = (
        _overlapping(
            ResourceRequirement.objects
            .filter(scope_q, kind=ResourceKind.EQUIPMENT)
            .select_related("equipment_category"),
            _REQ_START, _REQ_END, target_date, target_date)
        .values("equipment_category_id", "equipment_category__name")
        .annotate(total=Sum("quantity"))
    )

    assigned = (
        _overlapping(
            ResourceAllocation.objects
            .filter(scope_q, equipment__isnull=False),
            _ALLOC_START, _ALLOC_END, target_date, target_date)
        .values("equipment__category_id", "equipment__category__name")
        .annotate(total=Count("id", distinct=True))
    )

    rows: dict[int | None, dict] = {}
    for row in planned:
        key = row["equipment_category_id"]
        rows.setdefault(key, {
            "category_id": key,
            "category_name": row["equipment_category__name"],
            "planned": 0, "assigned": 0,
        })["planned"] = int(row["total"] or 0)
    for row in assigned:
        key = row["equipment__category_id"]
        rows.setdefault(key, {
            "category_id": key,
            "category_name": row["equipment__category__name"],
            "planned": 0, "assigned": 0,
        })["assigned"] = int(row["total"] or 0)

    # Без категории — последними: это «техника, которую не классифицировали»,
    # а не самостоятельный тип, и в начале списка она мешала бы.
    return sorted(rows.values(),
                  key=lambda r: (r["category_id"] is None,
                                 r["category_name"] or ""))


def usage_history(date_from: dt.date, date_to: dt.date, *,
                  category_id: int | None = None, **scope) -> list[dict]:
    """История: какая машина, на какой задаче и в какие даты была занята.

    Интервалами, а не сутками: «кара K-1 стояла на развозке валов с 3 по 12
    июня» — это одна строка, а не десять, и именно так историю читают.
    Разворачивать в дни, если понадобится S-кривая по технике, будет
    вызывающий — данных для этого здесь достаточно.
    """
    qs = ResourceAllocation.objects.filter(
        _scope_q("", **scope), equipment__isnull=False)
    if category_id is not None:
        qs = qs.filter(equipment__category_id=category_id)

    rows = _overlapping(
        qs.select_related("equipment", "equipment__category", "task",
                          "roadmap"),
        _ALLOC_START, _ALLOC_END, date_from, date_to,
    ).order_by("eff_start", "equipment__name")

    return [{
        "allocation_id": row.id,
        "equipment_id": row.equipment_id,
        "equipment_name": row.equipment.name,
        "inventory_no": row.equipment.inventory_no,
        "category_id": row.equipment.category_id,
        "category_name": (row.equipment.category.name
                          if row.equipment.category else None),
        "task_id": row.task_id,
        "task_key": row.task.key if row.task else None,
        "task_summary": row.task.summary if row.task else None,
        "roadmap_id": row.roadmap_id or (row.task.roadmap_id if row.task
                                         else None),
        "date_from": row.eff_start,
        "date_to": row.eff_end,
        # Дни занятости — календарные и всегда: это «сколько машина стояла
        # на объекте», а не плановая длительность работ. Выходные она с
        # объекта не уезжает.
        "days": (row.eff_end - row.eff_start).days + 1,
    } for row in rows]


__all__ = ["engaged_on", "usage_history"]
