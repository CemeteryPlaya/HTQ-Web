"""Ресурсы: потребность количеством и именное назначение.

Две таблицы, разделённые по времени, а не по типу ресурса:

* ``ResourceRequirement`` — план. «На развозку валов нужны 2 человека и
  2 кары». Известен на этапе планирования пакета, имён в нём нет и быть не
  может.
* ``ResourceAllocation`` — факт. «Кара K-1 и Иванов заняты на этой задаче».
  Появляется позже и может ссылаться на потребность, которую закрывает.

Обе висят либо на роудмапе, либо на задаче — тройка «график / люди /
техника» на доске повторена на обоих уровнях, и держать её двумя парами
почти одинаковых таблиц значило бы гарантированно их рассинхронизировать.

Назначения переехали сюда из ``task_content_service``: там они оказались
за компанию с комментариями и вложениями, а с появлением плана это
самостоятельный сюжет.
"""

from __future__ import annotations

from django.db import transaction
from django.db.models import Count, Q, Sum
from django.http import Http404

from .. import schemas
from ..models import (Equipment, ResourceAllocation, ResourceKind,
                      ResourceRequirement, Roadmap, Task)


def _require_task(task_id: int) -> Task:
    task = Task.objects.filter(pk=task_id, is_deleted=False).first()
    if task is None:
        raise Http404("Task not found")
    return task


def _require_roadmap(roadmap_id: int) -> Roadmap:
    roadmap = Roadmap.objects.filter(pk=roadmap_id).first()
    if roadmap is None:
        raise Http404("Roadmap not found")
    return roadmap


def _require_one_target(roadmap_id: int | None, task_id: int | None) -> None:
    """Ровно одна цель. Дублирует CHECK сознательно — здесь это 422 с
    человеческим текстом, а не IntegrityError, ставший 500."""
    if (roadmap_id is None) == (task_id is None):
        raise ValueError("Укажите ровно одно: roadmap_id или task_id")
    if task_id is not None:
        _require_task(task_id)
    else:
        _require_roadmap(roadmap_id)


# ── потребности (план количеством) ──────────────────────────────────────

def list_requirements(*, roadmap_id: int | None = None,
                      task_id: int | None = None) -> list[ResourceRequirement]:
    qs = ResourceRequirement.objects.select_related("work_role",
                                                    "equipment_category")
    if roadmap_id is not None:
        qs = qs.filter(roadmap_id=roadmap_id)
    if task_id is not None:
        qs = qs.filter(task_id=task_id)
    return list(qs.order_by("kind", "id"))


def get_requirement(requirement_id: int) -> ResourceRequirement:
    """Строка потребности — вьюхе, чтобы узнать цель и проверить права.

    Как ``allocation_target`` у назначений: ручка адресуется собственным id,
    и до резолва цели проверять доступ не на чем.
    """
    row = ResourceRequirement.objects.filter(pk=requirement_id).first()
    if row is None:
        raise Http404("Requirement not found")
    return row


def create_requirement(payload: dict) -> ResourceRequirement:
    _require_one_target(payload.get("roadmap_id"), payload.get("task_id"))
    kind = payload.get("kind")
    # Зеркалит ck_requirement_kind_fields: поле «не своего» вида молча
    # обнуляем, а не отказываем. Форма шлёт обе колонки, и переключение
    # вида в ней — обычное дело, а не ошибка оператора.
    if kind == ResourceKind.HUMAN:
        payload["equipment_category_id"] = None
    elif kind == ResourceKind.EQUIPMENT:
        payload["work_role_id"] = None
    return ResourceRequirement.objects.create(**payload)


def update_requirement(requirement_id: int, changes: dict) -> ResourceRequirement:
    row = get_requirement(requirement_id)
    for field, value in changes.items():
        setattr(row, field, value)
    if row.kind == ResourceKind.HUMAN:
        row.equipment_category_id = None
    else:
        row.work_role_id = None
    row.save()
    return row


def delete_requirement(requirement_id: int) -> None:
    """Потребность снимается с плана; уже назначенные ресурсы остаются.

    ``ResourceAllocation.requirement`` — ``SET_NULL``, так что назначения
    переживают удаление плана и просто перестают быть «плановыми». Терять
    вместе с планом людей, которые уже работают, было бы неверно.
    """
    get_requirement(requirement_id).delete()


def build_requirement(row: ResourceRequirement, *,
                      filled: int | None = None) -> dict:
    return {
        "id": row.id,
        "roadmap_id": row.roadmap_id,
        "task_id": row.task_id,
        "kind": str(row.kind),
        "work_role_id": row.work_role_id,
        "work_role_name": row.work_role.name if row.work_role else None,
        "equipment_category_id": row.equipment_category_id,
        "equipment_category_name": (row.equipment_category.name
                                    if row.equipment_category else None),
        "quantity": row.quantity,
        "filled": filled if filled is not None else row.allocations.count(),
        "start_date": row.start_date,
        "end_date": row.end_date,
        "note": row.note,
    }


def build_requirements(rows: list[ResourceRequirement]) -> list[dict]:
    """Список с числом закрытых мест — одним запросом на всю пачку."""
    filled = dict(
        ResourceAllocation.objects
        .filter(requirement__in=rows)
        .values_list("requirement_id")
        .annotate(n=Count("id"))
        .values_list("requirement_id", "n")
    )
    return [build_requirement(row, filled=filled.get(row.id, 0)) for row in rows]


# ── назначения (факт именами) ───────────────────────────────────────────

def allocation_target(allocation_id: int) -> tuple[int | None, int | None]:
    """``(task_id, roadmap_id)`` назначения — для проверки прав вызывающим.

    Назначение адресуется собственным id, так что вьюхе не на чем проверять
    доступ, пока она не узнает цель. ``Http404`` для неизвестного id — тот
    же ответ, что получит и посторонний после проверки видимости, так что
    сам по себе этот запрос ничего не выдаёт.
    """
    row = (ResourceAllocation.objects.filter(pk=allocation_id)
           .values("task_id", "roadmap_id").first())
    if row is None:
        raise Http404("Assignment not found")
    return row["task_id"], row["roadmap_id"]


def list_allocations(*, task_id: int | None = None,
                     roadmap_id: int | None = None) -> list[ResourceAllocation]:
    qs = ResourceAllocation.objects.all()
    if task_id is not None:
        qs = qs.filter(task_id=task_id)
    if roadmap_id is not None:
        qs = qs.filter(roadmap_id=roadmap_id)
    return list(qs.order_by("id"))


@transaction.atomic
def create_allocation(data: schemas.AssignmentCreate) -> ResourceAllocation:
    """Ровно один ресурс (человек или машина) и ровно одна цель.

    Проверки в приложении дают 422 с внятным текстом; констрейнты в БД
    существуют, чтобы правило нельзя было обойти другим путём записи.

    ``atomic`` не для отката, а ради блокировки в
    ``_require_matching_requirement``: без транзакции ``select_for_update``
    ничего не значит.
    """
    has_employee = data.employee_id is not None
    has_equipment = data.equipment_id is not None
    if has_employee == has_equipment:
        raise ValueError("Provide exactly one of employee_id or equipment_id")
    _require_one_target(data.roadmap_id, data.task_id)
    if has_equipment and not Equipment.objects.filter(
            pk=data.equipment_id).exists():
        raise Http404("Equipment not found")
    if data.requirement_id is not None:
        _require_matching_requirement(data)
    return ResourceAllocation.objects.create(**data.model_dump())


def _require_matching_requirement(data: schemas.AssignmentCreate) -> None:
    """Назначение по плану обязано попадать в тот же план и не переполнять его.

    Без этой проверки «закрыто 3 из 2» — достижимое состояние, и метрика
    план/факт начала бы показывать перевыполнение там, где на деле просто
    кликнули лишний раз.

    ``select_for_update`` на строке потребности: «посчитать и вставить» —
    классическая гонка, и два одновременных назначения на последнее
    свободное место оба увидели бы, что место есть. Блокируется потребность,
    а не таблица назначений, так что сериализуются только попытки закрыть
    ОДНУ И ТУ ЖЕ потребность. Тот же приём, что у счётчика ключей в
    ``sequence_service``.
    """
    req = (ResourceRequirement.objects.select_for_update()
           .filter(pk=data.requirement_id).first())
    if req is None:
        raise Http404("Requirement not found")
    if (req.roadmap_id, req.task_id) != (data.roadmap_id, data.task_id):
        raise ValueError("Потребность относится к другому роудмапу или задаче")
    expected = (ResourceKind.EQUIPMENT if data.equipment_id is not None
                else ResourceKind.HUMAN)
    if req.kind != expected:
        raise ValueError("Вид ресурса не совпадает с видом потребности")
    filled = req.allocations.count()
    if filled >= req.quantity:
        raise ValueError(
            f"Потребность уже закрыта: назначено {filled} из {req.quantity}")


def delete_allocation(allocation_id: int) -> None:
    row = ResourceAllocation.objects.filter(pk=allocation_id).first()
    if row is None:
        raise Http404("Assignment not found")
    row.delete()


def build_allocation(row: ResourceAllocation) -> schemas.AssignmentResponse:
    return schemas.AssignmentResponse.model_validate({
        "id": row.id, "task_id": row.task_id, "roadmap_id": row.roadmap_id,
        "requirement_id": row.requirement_id,
        "employee_id": row.employee_id, "equipment_id": row.equipment_id,
        "role": row.role, "allocation": row.allocation,
    })


# ── свёртка для метрики роудмапа ────────────────────────────────────────

def roadmap_resource_totals(roadmap_id: int) -> dict:
    """План и факт по людям и технике для одного роудмапа.

    План — сумма ``quantity`` потребностей САМОГО роудмапа: «на пакет нужно
    2 человека». Потребности его задач сюда не входят намеренно — это
    детализация того же плана уровнем ниже, и сложение дало бы двойной счёт.

    Факт — ``COUNT(DISTINCT)`` по назначениям роудмапа И его задач, потому
    что один человек, занятый на трёх задачах пакета, — это один человек, а
    не три. По той же причине сюда добавляются исполнители задач
    (``Task.assignee_id``): у задачи может не быть строки назначения, но
    исполнитель у неё есть, и в «сколько людей занято» он входит.
    """
    planned = dict(
        ResourceRequirement.objects.filter(roadmap_id=roadmap_id)
        .values_list("kind").annotate(total=Sum("quantity"))
        .values_list("kind", "total")
    )

    scope = Q(roadmap_id=roadmap_id) | Q(task__roadmap_id=roadmap_id,
                                         task__is_deleted=False)
    allocations = ResourceAllocation.objects.filter(scope)
    people = set(allocations.exclude(employee_id__isnull=True)
                 .values_list("employee_id", flat=True))
    people |= set(Task.objects
                  .filter(roadmap_id=roadmap_id, is_deleted=False,
                          assignee_id__isnull=False)
                  .values_list("assignee_id", flat=True))
    machines = set(allocations.exclude(equipment_id__isnull=True)
                   .values_list("equipment_id", flat=True))

    return {
        "human": _comparison(planned.get(ResourceKind.HUMAN), len(people)),
        "equipment": _comparison(planned.get(ResourceKind.EQUIPMENT),
                                 len(machines)),
    }


def _comparison(planned: int | None, actual: int) -> dict:
    return {
        "planned": int(planned) if planned is not None else None,
        "actual": actual,
        # None, а не 0: без плана сравнивать не с чем, и нарисованный ноль
        # читался бы как «расхождения нет».
        "delta": actual - int(planned) if planned is not None else None,
    }


__all__ = [
    "list_requirements", "get_requirement", "create_requirement", "update_requirement",
    "delete_requirement", "build_requirement", "build_requirements",
    "allocation_target", "list_allocations", "create_allocation",
    "delete_allocation", "build_allocation",
    "roadmap_resource_totals",
]
