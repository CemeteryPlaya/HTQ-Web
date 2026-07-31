"""Ежедневные отчёты и их ревизии — единственный источник факта выполнения.

Новый домен, FastAPI-оригинала нет.

Две вещи, из-за которых модуль вообще существует, а не сводится к CRUD:

* **Дата выполнения ≠ дата заполнения.** ``work_date`` ставит человек,
  ``created_at`` ставит система. Отчёт за пятницу заполняют в понедельник,
  и всё, что считается по дням (S-кривая, темп, прогноз), обязано
  раскладываться по ``work_date``. Ни одна выборка здесь не сортирует и не
  группирует по ``created_at``.
* **Каждая правка порождает ревизию.** Отчётность правят, и правки эти
  предметно значимы: цифра выполнения — основание для расчётов с
  подрядчиком. Модель ревизии — полный снимок, а не пара old/new: см.
  докстринг ``DailyReportRevision``.

Образец для копирования — ``approvals``: ``RequestFormTemplateVersion`` плюс
денормализованный ``current_version_id`` обычным числом.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from django.http import Http404

from ..models import (TERMINAL_STATUSES, DailyReport, DailyReportRevision,
                      Task, TaskVolume, WorkVolumeType)
from . import hydration
from . import task_service

# Поля, которые составляют СОДЕРЖАНИЕ отчёта: их правка создаёт ревизию.
# ``volume_type`` сюда не входит намеренно — смена вида работ это другой
# отчёт, а не другая версия этого (см. ``update_report``).
REVISIONED_FIELDS = ("work_date", "quantity", "headcount", "comment")


def _require_task(task_id: int) -> Task:
    task = Task.objects.filter(pk=task_id, is_deleted=False).first()
    if task is None:
        raise Http404("Task not found")
    return task


def get_report(report_id: int) -> DailyReport:
    """Отчёт вместе с задачей — вызывающему она нужна для проверки прав."""
    report = (DailyReport.objects.select_related("task", "volume_type")
              .filter(pk=report_id, is_deleted=False).first())
    if report is None:
        raise Http404("Daily report not found")
    return report


def list_reports(*, task_id: int | None = None, roadmap_id: int | None = None,
                 date_from: dt.date | None = None,
                 date_to: dt.date | None = None) -> list[DailyReport]:
    qs = (DailyReport.objects.filter(is_deleted=False)
          .select_related("task", "volume_type"))
    if task_id is not None:
        qs = qs.filter(task_id=task_id)
    if roadmap_id is not None:
        qs = qs.filter(task__roadmap_id=roadmap_id)
    if date_from is not None:
        qs = qs.filter(work_date__gte=date_from)
    if date_to is not None:
        qs = qs.filter(work_date__lte=date_to)
    # По дате выполнения, не заполнения: лента читается как хроника работ.
    # ``-id`` вторым ключом — чтобы несколько смен одного дня шли стабильно.
    return list(qs.order_by("-work_date", "-id"))


def _require_volume_type(volume_type_id: int) -> None:
    if not WorkVolumeType.objects.filter(pk=volume_type_id).exists():
        raise ValueError(f"Вид объёма работ {volume_type_id} не найден")


def resolve_volume_type(task: Task, volume_type_id: int | None) -> int:
    """Вид работ отчёта: присланный или единственный у задачи.

    Подстановка не «удобство», а условие того, чтобы форма не спрашивала
    очевидное: у большинства задач вид работ один, и заставлять выбирать
    из списка в один элемент — лишний клик на каждую смену. Когда видов
    несколько, угадывать нельзя, и сервис отказывает.
    """
    if volume_type_id is not None:
        _require_volume_type(volume_type_id)
        return volume_type_id

    ids = list(task.volumes.values_list("volume_type_id", flat=True))
    if len(ids) == 1:
        return ids[0]
    if not ids:
        raise ValueError(
            "У задачи не задан плановый объём работ — укажите вид работ "
            "явно или заполните объёмы задачи.")
    raise ValueError("У задачи несколько видов работ — укажите, по какому "
                     "из них отчёт.")


@transaction.atomic
def create_report(task_id: int, payload: dict, *,
                  author_id: int | None) -> DailyReport:
    """Создать отчёт и его первую ревизию.

    Ревизия 1 пишется сразу, а не при первой правке: история должна
    начинаться с исходного состояния, иначе «что было до правки» пришлось
    бы восстанавливать вычитанием, а для самого первого значения — ниоткуда.
    """
    task = _require_task(task_id)
    volume_type_id = resolve_volume_type(task, payload.get("volume_type_id"))

    report = DailyReport.objects.create(
        task=task,
        volume_type_id=volume_type_id,
        author_id=author_id,
        work_date=payload["work_date"],
        quantity=payload["quantity"],
        headcount=payload.get("headcount"),
        comment=payload.get("comment") or "",
        current_revision=1,
    )
    _snapshot(report, edited_by_id=author_id)
    return report


@transaction.atomic
def update_report(report_id: int, changes: dict, *,
                  editor_id: int | None) -> DailyReport:
    """Правка отчёта: новая ревизия + обновлённая строка.

    Номер ревизии инкрементится по ``current_revision`` отчёта, а не по
    ``COUNT(*)`` ревизий: счётчик — денормализация ради этой самой операции,
    и пересчитывать его каждый раз значило бы держать её зря.

    Правка, ничего не меняющая по существу, ревизию НЕ создаёт: лента
    версий должна отвечать «что и когда исправили», а не «сколько раз
    открывали форму».
    """
    report = get_report(report_id)

    if "volume_type_id" in changes and changes["volume_type_id"] not in (
            None, report.volume_type_id):
        # Не «нельзя технически», а «это другой отчёт»: сумма факта
        # ключуется парой (задача, вид работ), и подмена вида задним числом
        # перенесла бы объём между видами, не оставив следа в ленте.
        raise ValueError("Вид работ у отчёта не меняется — удалите отчёт и "
                         "заведите новый по нужному виду.")
    changes.pop("volume_type_id", None)

    touched = {field: value for field, value in changes.items()
               if field in REVISIONED_FIELDS
               and getattr(report, field) != value}
    if not touched:
        return report

    for field, value in touched.items():
        setattr(report, field, value)
    report.current_revision += 1
    report.save(update_fields=[*touched, "current_revision", "updated_at"])
    _snapshot(report, edited_by_id=editor_id)
    return report


def delete_report(report_id: int) -> None:
    """Мягкое удаление. Ревизию не создаёт: удаление не меняет содержания,
    а сам факт виден по ``is_deleted``."""
    report = get_report(report_id)
    report.is_deleted = True
    report.save(update_fields=["is_deleted", "updated_at"])


def _snapshot(report: DailyReport, *, edited_by_id: int | None) -> None:
    DailyReportRevision.objects.create(
        report=report,
        revision_no=report.current_revision,
        work_date=report.work_date,
        quantity=report.quantity,
        headcount=report.headcount,
        comment=report.comment,
        edited_by_id=edited_by_id,
    )


def list_revisions(report_id: int) -> list[DailyReportRevision]:
    get_report(report_id)      # 404 раньше пустого списка
    return list(DailyReportRevision.objects.filter(report_id=report_id))


# ── свёртки факта ───────────────────────────────────────────────────────

def completed_by_volume_type(*, task_ids=None, roadmap_id=None,
                             block_id=None, upto: dt.date | None = None
                             ) -> dict[tuple[int, int], Decimal]:
    """Факт по парам (задача, вид работ): ``{(task_id, type_id): Σ quantity}``.

    ``upto`` — отчётная дата: считаются только отчёты с ``work_date <= D``.
    Без неё берётся всё. Это и есть то, что раньше лежало в
    ``TaskVolume.completed_quantity``, но теперь его можно спросить на
    ЛЮБУЮ дату, а не только «сейчас».

    Одним запросом на всю выборку: конвенция ``_metrics_batch``.
    """
    qs = _scoped(
        DailyReport.objects.filter(is_deleted=False, task__is_deleted=False),
        task_ids=task_ids, roadmap_id=roadmap_id, upto=upto)
    if block_id is not None:
        qs = qs.filter(task__site_block_id=block_id)

    return {
        (row["task_id"], row["volume_type_id"]): row["total"] or Decimal("0")
        for row in qs.values("task_id", "volume_type_id").annotate(
            total=Sum("quantity"))
    }


def _scoped(qs, *, roadmap_id=None, task_id=None, project_id=None,
            task_ids=None, upto=None):
    """Общее сужение выборки отчётов. Один набор фильтров на все свёртки —
    иначе «а этот учитывает удалённые задачи?» пришлось бы выяснять в
    каждой заново."""
    if roadmap_id is not None:
        qs = qs.filter(task__roadmap_id=roadmap_id)
    if project_id is not None:
        qs = qs.filter(task__project_id=project_id)
    if task_id is not None:
        qs = qs.filter(task_id=task_id)
    if task_ids is not None:
        qs = qs.filter(task_id__in=list(task_ids))
    if upto is not None:
        qs = qs.filter(work_date__lte=upto)
    return qs


def daily_series_by_task(*, task_ids, upto: dt.date | None = None
                         ) -> list[dict]:
    """Факт по дням с разбивкой по задачам — одним запросом на пачку.

    Нужна для темпа: он меряется по каждой задаче отдельно, и запрос на
    задачу в цикле был бы N+1 ровно там, где задач больше всего.
    """
    qs = _scoped(
        DailyReport.objects.filter(is_deleted=False, task__is_deleted=False),
        task_ids=task_ids, upto=upto)
    return [{"task_id": row["task_id"], "date": row["work_date"],
             "quantity": row["total"] or Decimal("0")}
            for row in qs.values("task_id", "work_date")
            .annotate(total=Sum("quantity")).order_by("task_id", "work_date")]


def daily_series(*, roadmap_id: int | None = None, task_id: int | None = None,
                 project_id: int | None = None,
                 upto: dt.date | None = None) -> list[dict]:
    """Факт по дням: ``[{date, quantity}]``, отсортировано по дате.

    Строго по ``work_date`` — ради этого отчёты и заведены. Накопительный
    итог здесь НЕ считается: S-кривой нужен и план, а он живёт в
    ``plan_fact_service``; складывать их надо в одном месте, а не двух.
    """
    qs = _scoped(
        DailyReport.objects.filter(is_deleted=False, task__is_deleted=False),
        roadmap_id=roadmap_id, task_id=task_id, project_id=project_id,
        upto=upto)
    return [{"date": row["work_date"], "quantity": row["total"] or Decimal("0")}
            for row in qs.values("work_date").annotate(total=Sum("quantity"))
            .order_by("work_date")]


# ── ответы ──────────────────────────────────────────────────────────────

def build_reports(reports: list[DailyReport]) -> list[dict]:
    """Одна волна гидрации авторов на весь список (инвариант task_response)."""
    users = hydration.user_briefs([r.author_id for r in reports])
    return [{
        "id": row.id,
        "task_id": row.task_id,
        "task_key": row.task.key,
        "volume_type_id": row.volume_type_id,
        "volume_type_name": row.volume_type.name,
        "unit": str(row.volume_type.unit),
        "author_id": row.author_id,
        "author_name": hydration.user_name(users, row.author_id),
        "work_date": row.work_date,
        "quantity": float(row.quantity),
        "headcount": row.headcount,
        "comment": row.comment,
        "current_revision": row.current_revision,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    } for row in reports]


def build_report(report: DailyReport) -> dict:
    return build_reports([report])[0]


def build_revisions(rows: list[DailyReportRevision]) -> list[dict]:
    users = hydration.user_briefs([r.edited_by_id for r in rows])
    return [{
        "id": row.id,
        "report_id": row.report_id,
        "revision_no": row.revision_no,
        "work_date": row.work_date,
        "quantity": float(row.quantity),
        "headcount": row.headcount,
        "comment": row.comment,
        "edited_by_id": row.edited_by_id,
        "edited_by_name": hydration.user_name(users, row.edited_by_id),
        "edited_at": row.edited_at,
    } for row in rows]


# ── сводка «что отчитать за день» ───────────────────────────────────────

def reporting_board(*, on: dt.date, user_id: int | None,
                    elevated: bool) -> list[dict]:
    """Задачи, по которым вызывающий отчитывается, с фактом на дату ``on``.

    Ради этой выборки существует отдельная страница ежедневки: собирать её
    на фронте значило бы дёрнуть список задач, а потом карточку каждой —
    объёмы приходят только в детальном ответе. Здесь всё одним запросом на
    сущность: задачи, объёмы, накопленный факт, отчёты за саму дату.

    **Показываются только те задачи, куда сохранение пройдёт.** Отбор идёт
    по ``task_service.soft_edit_q`` — тому же правилу, что проверяет запись,
    — иначе строка на экране означала бы 403 при попытке заполнить её.
    Админ видит все: он вправе отчитаться где угодно.

    Задачи БЕЗ планового объёма отсеиваются: вид работ у отчёта берётся
    оттуда, и без него отчёт невозможен (``resolve_volume_type``).
    Терминальные — тоже: отчитываться о закрытой работе нечего.
    """
    tasks = (Task.objects
             .filter(is_deleted=False, volumes__isnull=False)
             .exclude(status__in=TERMINAL_STATUSES)
             .select_related("project", "site", "site_block", "roadmap")
             .distinct())
    if not elevated:
        if user_id is None:
            return []
        tasks = tasks.filter(task_service.soft_edit_q(user_id))
    tasks = list(tasks.order_by("site_block__name", "start_date", "id"))
    if not tasks:
        return []

    ids = [task.id for task in tasks]

    planned: dict[int, list] = {}
    for row in (TaskVolume.objects.filter(task_id__in=ids)
                .select_related("volume_type")
                .order_by("volume_type__name")):
        planned.setdefault(row.task_id, []).append(row)

    # Факт нарастающим итогом — на дату, а не «всего»: строка показывает,
    # сколько сделано К ЭТОМУ дню, и завтрашние отчёты её не меняют.
    completed = completed_by_volume_type(task_ids=ids, upto=on)

    today_rows = list(DailyReport.objects
                      .filter(task_id__in=ids, work_date=on, is_deleted=False)
                      .select_related("task", "volume_type")
                      .order_by("id"))
    by_task: dict[int, list] = {}
    for row in today_rows:
        by_task.setdefault(row.task_id, []).append(row)
    reports_payload = {row["id"]: row for row in build_reports(today_rows)}

    return [{
        "task_id": task.id,
        "key": task.key,
        "summary": task.summary,
        "status": str(task.status),
        "project_name": task.project.name if task.project else None,
        "site_name": task.site.name if task.site else None,
        "site_block_name": task.site_block.name if task.site_block else None,
        "roadmap_id": task.roadmap_id,
        "roadmap_name": task.roadmap.name if task.roadmap else None,
        "due_date": task.due_date,
        "volumes": [{
            "volume_type_id": row.volume_type_id,
            "volume_type_name": row.volume_type.name,
            "unit": str(row.volume_type.unit),
            "planned_quantity": float(row.planned_quantity),
            "completed_quantity": float(
                completed.get((task.id, row.volume_type_id)) or 0),
        } for row in planned.get(task.id, [])],
        "reports": [reports_payload[row.id]
                    for row in by_task.get(task.id, [])],
    } for task in tasks]


__all__ = [
    "REVISIONED_FIELDS",
    "get_report", "list_reports", "create_report", "update_report",
    "delete_report", "list_revisions", "resolve_volume_type",
    "completed_by_volume_type", "daily_series", "daily_series_by_task",
    "reporting_board",
    "build_report", "build_reports", "build_revisions",
]
