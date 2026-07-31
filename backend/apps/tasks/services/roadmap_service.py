"""Роудмапы — пакеты работ на блоке, уровень между блоком и задачей.

Новый домен, FastAPI-оригинала нет.

Главное здесь — ``roadmap_metrics``: сравнение ПЛАНА, введённого руками
(«4 недели, 2 человека, 2 кары»), с ФАКТОМ, свёрнутым из задач. Факт нигде
не хранится специально, он всегда пересчитывается: копия разошлась бы с
задачами при первом же их изменении, и никто бы этого не заметил.

Площадка у роудмапа своей колонки не имеет — она выводится через
``site_block__site``, поэтому все фильтры и джойны по площадке идут именно
так. Правило «площадка блока входит в объекты проекта» живёт здесь, а
близнецы про объект и блок задачи — в ``site_service``: у всех причина одна
(правило про несколько таблиц, CheckConstraint видит одну строку одной), но
каждое стоит рядом со своей сущностью.
"""

from __future__ import annotations

from django.db.models import Case, Count, F, IntegerField, Max, Min, Q, Sum, When
from django.http import Http404

from ..models import (TERMINAL_STATUSES, Project, ProjectSite, Roadmap,
                      RoadmapStatus, SiteBlock, Task, TaskVolume)
from . import hydration


def scope_for(token) -> tuple[bool, int | None]:
    """``(employee_scope, department_id)`` — как у проектов, буква в букву:
    роудмап наследует ту же ось видимости, и расходиться им незачем."""
    if token.is_elevated:
        return False, None
    return True, hydration.employee_department_id(token.user_id)


def _visible(employee_scope: bool, department_id: int | None):
    qs = Roadmap.objects.all()
    if employee_scope:
        if department_id is None:
            return Roadmap.objects.none()
        # Отдел проекта тоже считается своим: роудмап часто заводят без
        # собственного отдела, и без этого он пропал бы из списка у всех.
        qs = qs.filter(Q(department_id=department_id)
                       | Q(department_id__isnull=True,
                           project__department_id=department_id))
    return qs


def list_roadmaps(*, employee_scope: bool, department_id: int | None,
                  project_id: int | None = None, site_id: int | None = None,
                  block_id: int | None = None,
                  status: str | None = None) -> list[Roadmap]:
    qs = (_visible(employee_scope, department_id)
          .select_related("project", "site_block", "site_block__site"))
    if project_id is not None:
        qs = qs.filter(project_id=project_id)
    if site_id is not None:
        # Через блок: своей колонки площадки у роудмапа нет.
        qs = qs.filter(site_block__site_id=site_id)
    if block_id is not None:
        qs = qs.filter(site_block_id=block_id)
    if status:
        qs = qs.filter(status=status)
    return list(qs.order_by("order",
                            F("planned_start_date").asc(nulls_last=True),
                            "name"))


def get_roadmap(roadmap_id: int, *, employee_scope: bool,
                department_id: int | None) -> Roadmap:
    roadmap = (_visible(employee_scope, department_id)
               .select_related("project", "site_block", "site_block__site")
               .filter(pk=roadmap_id).first())
    if roadmap is None:
        raise Http404("Roadmap not found")
    return roadmap


def require_project_block(project_id: int, block_id: int) -> int:
    """Площадка блока обязана входить в объекты проекта. Возвращает её id.

    Пустой набор объектов у проекта разрешает любой блок — то же
    послабление и по той же причине, что в ``site_service`` (у существующих
    проектов объектов нет, строгая проверка сломала бы их разом).

    Отдаёт ``site_id`` не «на всякий случай»: вызывающим он нужен сразу
    после проверки (``resolve_task_roadmap`` кладёт его в задачу), а второй
    поход в БД за уже прочитанным значением был бы лишним.
    """
    if not Project.objects.filter(pk=project_id).exists():
        raise ValueError(f"Проект {project_id} не найден")
    site_id = (SiteBlock.objects.filter(pk=block_id)
               .values_list("site_id", flat=True).first())
    if site_id is None:
        raise ValueError(f"Блок {block_id} не найден")
    allowed = set(ProjectSite.objects.filter(project_id=project_id)
                  .values_list("site_id", flat=True))
    if allowed and site_id not in allowed:
        raise ValueError(
            "Блок не относится к выбранному проекту. "
            "Выберите блок на одном из объектов проекта."
        )
    return site_id


def create_roadmap(payload: dict, *, creator_id: int | None) -> Roadmap:
    require_project_block(payload["project_id"], payload["site_block_id"])
    if payload.get("owner_id") is None:
        payload["owner_id"] = creator_id
    return Roadmap.objects.create(**payload)


def update_roadmap(roadmap_id: int, changes: dict) -> Roadmap:
    roadmap = Roadmap.objects.filter(pk=roadmap_id).first()
    if roadmap is None:
        raise Http404("Roadmap not found")
    # По итоговой паре, а не по присланным полям: проект и блок могут
    # приехать в одном PATCH (та же логика, что в ``task_service``).
    if "project_id" in changes or "site_block_id" in changes:
        require_project_block(
            changes.get("project_id", roadmap.project_id),
            changes.get("site_block_id", roadmap.site_block_id))
    for field, value in changes.items():
        setattr(roadmap, field, value)
    roadmap.save()
    return roadmap


class RoadmapInUse(Exception):
    """Роудмап нельзя удалить: в нём есть задачи.

    Раньше удаление разрешалось — ``Task.roadmap`` это ``SET_NULL``, и
    задачи просто теряли принадлежность пакету. Для плана строительства это
    оказалось слишком мягко: пакет несёт сроки и потребности, по которым
    считается отставание, и «разгруппировать» его одним кликом означает
    молча обнулить план по целому фронту работ. Мягкая альтернатива есть и
    она правильная — статус ``archived``.

    Та же логика и тот же выход, что у ``site_service.SiteInUse`` и
    ``block_service.BlockInUse``.
    """

    def __init__(self, tasks: int):
        self.tasks = tasks
        super().__init__(
            f"Роудмап используется: задач — {tasks}. "
            f"Переведите его в архив вместо удаления."
        )


def delete_roadmap(roadmap_id: int) -> None:
    roadmap = Roadmap.objects.filter(pk=roadmap_id).first()
    if roadmap is None:
        raise Http404("Roadmap not found")
    tasks = Task.objects.filter(roadmap_id=roadmap_id, is_deleted=False).count()
    if tasks:
        raise RoadmapInUse(tasks)
    roadmap.delete()


# ── валидация роудмапа задачи ───────────────────────────────────────────

def resolve_task_roadmap(project_id: int | None, site_id: int | None,
                         block_id: int | None, roadmap_id: int | None
                         ) -> tuple[int | None, int | None, int | None,
                                    int | None]:
    """Согласовать четвёрку (проект, площадка, блок, роудмап) задачи.

    Роудмап знает всё три верхних уровня, поэтому он их ЗАДАЁТ, а не
    проверяется против них: выбрал пакет работ — проект, площадка и блок
    следуют из него. Если задача уже висела на другом проекте или блоке,
    это не конфликт, а переезд — ровно то, что человек и имел в виду,
    выбирая роудмап.

    Блок в четвёрке появился вместе с переездом роудмапа на блок: раньше
    пакет накрывал площадку целиком, и блок задачи оставался её личным
    делом. Теперь задача пакета не может стоять на чужом блоке.

    Возвращает итоговую четвёрку. Кортеж, а не запись в словарь по месту:
    оба вызывающих (create/update) дальше кладут значения по-разному.
    """
    if roadmap_id is None:
        return project_id, site_id, block_id, None

    row = (Roadmap.objects.filter(pk=roadmap_id)
           .values("project_id", "site_block_id", "site_block__site_id").first())
    if row is None:
        raise ValueError(f"Роудмап {roadmap_id} не найден")
    return (row["project_id"], row["site_block__site_id"],
            row["site_block_id"], roadmap_id)


# ── план против факта ───────────────────────────────────────────────────

def roadmap_metrics(roadmap: Roadmap) -> dict:
    """План (введён руками) против факта (свёрнут из задач).

    Три оси доски — срок, люди, техника — плюс прогресс. По каждой отдаётся
    ``planned``, ``actual`` и ``delta``; ``delta`` считается только когда
    известны обе стороны, иначе это не «ноль расхождения», а «сравнивать не
    с чем».

    Ресурсную часть считает ``resource_service.roadmap_resource_totals``:
    там же, где живут обе таблицы, и там же, где знают, что один человек на
    трёх задачах пакета — это один человек.
    """
    tasks = Task.objects.filter(roadmap_id=roadmap.id, is_deleted=False)

    agg = tasks.aggregate(
        task_count=Count("id"),
        done_count=Sum(Case(When(status__in=list(TERMINAL_STATUSES), then=1),
                            default=0, output_field=IntegerField())),
        actual_start=Min("start_date"),
        actual_end=Max("due_date"),
    )
    task_count = int(agg["task_count"] or 0)
    done_count = int(agg["done_count"] or 0)

    # Мера длительности — свойство ПРОЕКТА, и она одна для плана и факта:
    # посчитать план в календарных, а факт в рабочих значило бы показать
    # расхождение там, где его нет (ровно этим код и грешил до флага).
    working = roadmap.project.use_production_calendar
    actual_days = _days_between(agg["actual_start"], agg["actual_end"], working)
    planned_days = roadmap.planned_working_days
    if planned_days is None:
        planned_days = _days_between(roadmap.planned_start_date,
                                     roadmap.planned_end_date, working)

    # Локальный импорт: resource_service тянет ResourceAllocation и
    # ResourceRequirement, а этому модулю они нужны только здесь.
    from .resource_service import roadmap_resource_totals
    resources = roadmap_resource_totals(roadmap.id)

    return {
        "roadmap_id": roadmap.id,
        "task_count": task_count,
        "done_count": done_count,
        "progress": _progress(roadmap.id, task_count, done_count),
        "schedule": {
            "planned_start_date": roadmap.planned_start_date,
            "planned_end_date": roadmap.planned_end_date,
            "planned_working_days": planned_days,
            "actual_start_date": agg["actual_start"],
            "actual_end_date": agg["actual_end"],
            "actual_working_days": actual_days,
            "delta_working_days": (actual_days - planned_days
                                   if planned_days is not None
                                   and actual_days is not None else None),
        },
        "human": resources["human"],
        "equipment": resources["equipment"],
    }


def _progress(roadmap_id: int, task_count: int, done_count: int) -> float | None:
    """Процент по ШТУКАМ, если у задач заданы объёмы; иначе по статусам.

    Порядок именно такой: «развезли 180 валов из 250» — это то, что человек
    считает прогрессом, а «две задачи из трёх закрыты» — суррогат, которым
    приходится обходиться, когда объёмов нет. Возврат к статусам не
    «запасной путь на всякий случай», а нормальный режим для задач без
    измеримого объёма (согласование, выезд, приёмка).
    """
    planned = (TaskVolume.objects
               .filter(task__roadmap_id=roadmap_id, task__is_deleted=False)
               .aggregate(total=Sum("planned_quantity"))["total"])
    if planned:
        # Факт — сумма ежедневных отчётов пакета (см. daily_report_service).
        from .daily_report_service import completed_by_volume_type
        completed = sum(completed_by_volume_type(roadmap_id=roadmap_id).values())
        return round(min(float(completed) / float(planned), 1.0) * 100, 1)
    if task_count:
        return round(done_count / task_count * 100, 1)
    return None


def _days_between(start, end, working: bool) -> int | None:
    """Длительность отрезка в мере, заданной проектом.

    Импорт локальный, чтобы не тащить весь календарь событий в модуль про
    планирование работ.
    """
    if start is None or end is None:
        return None
    from .calendar_service import days_between
    return days_between(start, end, working=working)


# ── ответы ──────────────────────────────────────────────────────────────

def _metrics_batch(roadmap_ids: list[int]) -> dict[int, dict]:
    """Счётчики задач для списка — одним запросом на всю пачку."""
    rows = (Task.objects.filter(is_deleted=False, roadmap_id__in=roadmap_ids)
            .values("roadmap_id")
            .annotate(
                task_count=Count("id", distinct=True),
                done_count=Sum(Case(
                    When(status__in=list(TERMINAL_STATUSES), then=1),
                    default=0, output_field=IntegerField())),
            ))
    return {row["roadmap_id"]: row for row in rows}


def build_responses(roadmaps: list[Roadmap]) -> list[dict]:
    """Одна волна гидрации и один запрос счётчиков на весь список."""
    counts = _metrics_batch([r.id for r in roadmaps])
    users = hydration.user_briefs([r.owner_id for r in roadmaps])
    departments = hydration.department_briefs(
        [r.department_id for r in roadmaps])

    out = []
    for roadmap in roadmaps:
        row = counts.get(roadmap.id, {})
        task_count = int(row.get("task_count") or 0)
        done_count = int(row.get("done_count") or 0)
        out.append({
            "id": roadmap.id,
            "project_id": roadmap.project_id,
            "project_name": roadmap.project.name,
            # Площадка — через блок: своей колонки у роудмапа нет.
            "site_block_id": roadmap.site_block_id,
            "site_block_name": roadmap.site_block.name,
            "site_id": roadmap.site_block.site_id,
            "site_name": roadmap.site_block.site.name,
            "site_color": roadmap.site_block.site.color,
            "name": roadmap.name,
            "description": roadmap.description,
            "status": str(roadmap.status),
            "color": roadmap.color,
            "order": roadmap.order,
            "planned_start_date": roadmap.planned_start_date,
            "planned_end_date": roadmap.planned_end_date,
            "planned_working_days": roadmap.planned_working_days,
            "owner_id": roadmap.owner_id,
            "owner_name": hydration.user_name(users, roadmap.owner_id),
            "department_id": roadmap.department_id,
            "department_name": hydration.department_name(
                departments, roadmap.department_id),
            "task_count": task_count,
            "done_count": done_count,
            # Дешёвый прогресс по статусам — на карточку в списке. Точный,
            # по объёмам, считает ``roadmap_metrics`` для детальной.
            "progress": (round(done_count / task_count * 100, 1)
                         if task_count else 0.0),
            "created_at": roadmap.created_at,
            "updated_at": roadmap.updated_at,
        })
    return out


def build_response(roadmap: Roadmap) -> dict:
    return build_responses([roadmap])[0]


__all__ = [
    "RoadmapStatus", "RoadmapInUse",
    "scope_for", "list_roadmaps", "get_roadmap", "create_roadmap",
    "update_roadmap", "delete_roadmap",
    "require_project_block", "resolve_task_roadmap", "roadmap_metrics",
    "build_response", "build_responses",
]
