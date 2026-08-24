"""Ежедневные отчёты по ПЕРСОНАЛУ проекта: сколько людей и каких ролей.

Новый домен, FastAPI-оригинала нет.

Вторая ось факта, ортогональная ``daily_report_service``. Тот отвечает
«сколько сделано» (выработка в штуках по видам работ), этот — «сколькими
людьми» (численность по ролям на блоке). До него численность в системе не
собиралась: ``DailyReport.headcount`` существует, но он про одну задачу и
одну смену, а спрашивают про объект — «сколько человек было на проекте
5 июня».

Три вещи, из-за которых модуль не сводится к CRUD:

* **Дата выхода ≠ дата заполнения.** ``work_date`` ставит человек,
  ``created_at`` — система. То же различие и по той же причине, что у
  ``daily_report_service``: ни одна выборка здесь не группирует по
  ``created_at``.
* **Численность — состояние, а не инкремент.** Отсюда
  ``UNIQUE(project, site_block, work_date)``, которого у ``DailyReport``
  нет намеренно (см. докстринг ``ProjectStaffReport``). Второй отчёт за тот
  же день — не вторая смена, а конфликт; исправляют правкой.
* **Каждая правка порождает ревизию**, и снимок включает строки: правят
  чаще всего именно их («монтажников было не 12, а 10»).

Доска (``staff_board``) кладёт рядом три числа на каждый блок: факт
отсюда, план из ``ResourceRequirement(kind=human)`` и сумму
``DailyReport.headcount`` за ту же дату. Последнее — первый агрегат в
кодовой базе, который это поле вообще читает.
"""

from __future__ import annotations

import datetime as dt

from django.db import transaction
from django.db.models import Q, Sum
from django.http import Http404

from htqweb.fallback import fallback

from ..models import (DailyReport, ProjectSite, ProjectStaffReport,
                      ProjectStaffReportLine, ProjectStaffReportRevision,
                      ResourceKind, ResourceRequirement, SiteBlock, WorkRole)
from . import hydration
from . import roadmap_service

# Поля ШАПКИ, чья правка создаёт ревизию. Строки версионируются отдельно —
# они коллекция, и сравнивать их приходится снимком (см. ``update_report``).
# Проект и блок сюда не входят намеренно: их смена — другой отчёт, а не
# другая версия этого.
REVISIONED_FIELDS = ("work_date", "comment")

# Псевдо-роль для плановых потребностей без указанной роли.
# ``ResourceRequirement.work_role`` nullable намеренно («нужно 2 человека,
# роль не важна»), и такой план обязан попасть в итог по блоку, даже если
# в разбивку по конкретным ролям его положить некуда.
UNSPECIFIED_ROLE_NAME = "Без указания роли"


# ── чтение ──────────────────────────────────────────────────────────────

def get_report(report_id: int) -> ProjectStaffReport:
    """Отчёт вместе с проектом и блоком — вызывающему они нужны для прав."""
    report = (ProjectStaffReport.objects
              .select_related("project", "site_block", "site_block__site")
              .prefetch_related("lines__work_role")
              .filter(pk=report_id, is_deleted=False).first())
    if report is None:
        raise Http404("Project staff report not found")
    return report


def list_reports(*, project_id: int | None = None,
                 block_id: int | None = None,
                 date_from: dt.date | None = None,
                 date_to: dt.date | None = None) -> list[ProjectStaffReport]:
    qs = (ProjectStaffReport.objects.filter(is_deleted=False)
          .select_related("project", "site_block", "site_block__site")
          .prefetch_related("lines__work_role"))
    if project_id is not None:
        qs = qs.filter(project_id=project_id)
    if block_id is not None:
        qs = qs.filter(site_block_id=block_id)
    if date_from is not None:
        qs = qs.filter(work_date__gte=date_from)
    if date_to is not None:
        qs = qs.filter(work_date__lte=date_to)
    # По дате выхода, не заполнения: лента читается как хроника объекта.
    return list(qs.order_by("-work_date", "site_block__name", "-id"))


# ── запись ──────────────────────────────────────────────────────────────

def _clean_lines(raw: list[dict] | None) -> list[dict]:
    """Проверить строки и вернуть их в каноническом виде.

    Дубль роли ловится здесь, а не констрейнтом: ``bulk_create`` отдал бы
    ``IntegrityError`` (500), а это ошибка ввода и должна быть 422 с
    внятным текстом.
    """
    if not raw:
        raise ValueError("Отчёт без строк не имеет смысла — укажите хотя бы "
                         "одну роль и количество людей.")

    seen: set[int] = set()
    cleaned: list[dict] = []
    for row in raw:
        role_id = row["work_role_id"]
        if role_id in seen:
            raise ValueError("Роль встречается в отчёте дважды — сложите "
                             "людей в одну строку.")
        seen.add(role_id)
        cleaned.append({"work_role_id": role_id,
                        "headcount": int(row["headcount"])})

    known = set(WorkRole.objects.filter(pk__in=seen)
                .values_list("id", flat=True))
    missing = seen - known
    if missing:
        raise ValueError(
            f"Рабочая роль {sorted(missing)[0]} не найдена в справочнике.")
    return cleaned


def _replace_lines(report: ProjectStaffReport, lines: list[dict]) -> None:
    report.lines.all().delete()
    ProjectStaffReportLine.objects.bulk_create([
        ProjectStaffReportLine(report=report, work_role_id=row["work_role_id"],
                               headcount=row["headcount"])
        for row in lines])


@transaction.atomic
def create_report(project_id: int, payload: dict, *,
                  author_id: int | None) -> ProjectStaffReport:
    """Создать отчёт со строками и его первую ревизию.

    Ревизия 1 пишется сразу, а не при первой правке — по той же причине,
    что в ``daily_report_service.create_report``: история должна начинаться
    с исходного состояния.
    """
    block_id = payload["site_block_id"]
    # Площадка блока обязана входить в объекты проекта. Правило и его
    # послабление («у проекта нет объектов ⇒ можно любой блок») живут в
    # одном месте на весь домен — второй копии тут быть не должно.
    roadmap_service.require_project_block(project_id, block_id)
    lines = _clean_lines(payload.get("lines"))

    work_date = payload["work_date"]
    if (ProjectStaffReport.objects
            .filter(project_id=project_id, site_block_id=block_id,
                    work_date=work_date, is_deleted=False).exists()):
        # Проверка перед констрейнтом: 422 с объяснением полезнее, чем 500
        # из IntegrityError. Гонку всё равно поймает сам констрейнт.
        raise ValueError(
            "Отчёт по этому блоку за эту дату уже заведён — откройте его и "
            "исправьте. Численность это состояние, а не сумма смен.")

    report = ProjectStaffReport.objects.create(
        project_id=project_id,
        site_block_id=block_id,
        author_id=author_id,
        work_date=work_date,
        comment=payload.get("comment") or "",
        current_revision=1,
    )
    _replace_lines(report, lines)
    _snapshot(report, edited_by_id=author_id)
    return get_report(report.id)


@transaction.atomic
def update_report(report_id: int, changes: dict, *,
                  editor_id: int | None) -> ProjectStaffReport:
    """Правка отчёта: новая ревизия + обновлённые шапка и строки.

    Номер ревизии инкрементится по ``current_revision``, а не по
    ``COUNT(*)`` — счётчик денормализован ради этой самой операции.

    Правка, ничего не меняющая по существу, ревизию НЕ создаёт: лента
    версий отвечает «что и когда исправили», а не «сколько раз открывали
    форму». Строки сравниваются нормализованным снимком, поэтому
    переставленный порядок строк правкой не считается.
    """
    report = get_report(report_id)

    for field in ("project_id", "site_block_id"):
        if field in changes and changes[field] not in (
                None, getattr(report, field)):
            # Не «нельзя технически», а «это другой отчёт»: перенос задним
            # числом сдвинул бы численность между блоками, не оставив следа
            # в ленте, и упёрся бы в UNIQUE на новом месте.
            raise ValueError(
                "Проект и блок у отчёта не меняются — удалите отчёт и "
                "заведите новый на нужном блоке.")
        changes.pop(field, None)

    touched = {field: value for field, value in changes.items()
               if field in REVISIONED_FIELDS
               and getattr(report, field) != value}

    lines_changed = False
    if "lines" in changes:
        lines = _clean_lines(changes["lines"])
        lines_changed = _lines_snapshot(report) != _lines_payload(lines)

    if not touched and not lines_changed:
        return report

    if touched:
        for field, value in touched.items():
            setattr(report, field, value)
    if lines_changed:
        _replace_lines(report, lines)

    report.current_revision += 1
    report.save(update_fields=[*touched, "current_revision", "updated_at"])
    report = get_report(report_id)
    _snapshot(report, edited_by_id=editor_id)
    return report


def delete_report(report_id: int) -> None:
    """Мягкое удаление. Ревизию не создаёт: удаление не меняет содержания,
    а сам факт виден по ``is_deleted``. Строки остаются — они часть
    исправленной отчётности, а не мусор."""
    report = get_report(report_id)
    report.is_deleted = True
    report.save(update_fields=["is_deleted", "updated_at"])


# ── ревизии ─────────────────────────────────────────────────────────────

def _lines_payload(lines: list[dict]) -> list[dict]:
    """Канонический вид строк для СРАВНЕНИЯ: только id и количество,
    отсортировано. Имя роли сюда не входит — переименование роли в
    справочнике не является правкой отчёта."""
    return sorted(({"work_role_id": row["work_role_id"],
                    "headcount": row["headcount"]} for row in lines),
                  key=lambda row: row["work_role_id"])


def _lines_snapshot(report: ProjectStaffReport) -> list[dict]:
    return _lines_payload([{"work_role_id": row.work_role_id,
                            "headcount": row.headcount}
                           for row in report.lines.all()])


def _snapshot(report: ProjectStaffReport, *,
              edited_by_id: int | None) -> None:
    # ``select_related``, а не ``all()``: снимку нужно имя роли на каждой
    # строке, и через prefetch-кэш шапки его может не оказаться.
    rows = list(report.lines.select_related("work_role"))
    ProjectStaffReportRevision.objects.create(
        report=report,
        revision_no=report.current_revision,
        work_date=report.work_date,
        comment=report.comment,
        total_headcount=sum(row.headcount for row in rows),
        # Имя роли кладём В СНИМОК: снимок обязан читаться, даже если роль
        # потом переименовали или деактивировали.
        lines=[{"work_role_id": row.work_role_id,
                "work_role_name": row.work_role.name,
                "headcount": row.headcount} for row in rows],
        edited_by_id=edited_by_id,
    )


def list_revisions(report_id: int) -> list[ProjectStaffReportRevision]:
    get_report(report_id)      # 404 раньше пустого списка
    return list(ProjectStaffReportRevision.objects.filter(report_id=report_id))


# ── ответы ──────────────────────────────────────────────────────────────

def build_reports(reports: list[ProjectStaffReport]) -> list[dict]:
    """Одна волна гидрации авторов на весь список (инвариант task_response)."""
    users = hydration.user_briefs([r.author_id for r in reports])
    return [_report_payload(row, users) for row in reports]


def build_report(report: ProjectStaffReport) -> dict:
    return build_reports([report])[0]


def _report_payload(row: ProjectStaffReport, users: dict) -> dict:
    lines = list(row.lines.all())
    return {
        "id": row.id,
        "project_id": row.project_id,
        "project_name": row.project.name,
        "site_id": row.site_block.site_id,
        "site_name": row.site_block.site.name,
        "site_block_id": row.site_block_id,
        "site_block_name": row.site_block.name,
        "work_date": row.work_date,
        "author_id": row.author_id,
        "author_name": hydration.user_name(users, row.author_id),
        "comment": row.comment,
        "total_headcount": sum(line.headcount for line in lines),
        "lines": [{"work_role_id": line.work_role_id,
                   "work_role_name": line.work_role.name,
                   "headcount": line.headcount} for line in lines],
        "current_revision": row.current_revision,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def build_revisions(rows: list[ProjectStaffReportRevision]) -> list[dict]:
    users = hydration.user_briefs([r.edited_by_id for r in rows])
    return [{
        "id": row.id,
        "report_id": row.report_id,
        "revision_no": row.revision_no,
        "work_date": row.work_date,
        "comment": row.comment,
        "total_headcount": row.total_headcount,
        "lines": row.lines,
        "edited_by_id": row.edited_by_id,
        "edited_by_name": hydration.user_name(users, row.edited_by_id),
        "edited_at": row.edited_at,
    } for row in rows]


# ── свёртки для доски ───────────────────────────────────────────────────

def _group_total(row: dict, *, site: str) -> int:
    """``Sum(...)`` группы в ``int``. NULL тут не бывает — потому и громко.

    Группы в ``values().annotate()`` пустыми не бывают, а оба суммируемых
    поля не могут быть NULL: ``ResourceRequirement.quantity`` объявлен NOT
    NULL, а ``DailyReport.headcount`` отфильтрован ``headcount__isnull=False``.
    Значит NULL здесь означает не «нет данных», а «модель изменилась, и
    свёртка теперь врёт нулём» — то самое «этого не бывает», о котором надо
    узнавать сразу, а не по разъехавшимся цифрам на доске.
    """
    total = row["total"]
    if total is None:
        total = fallback(site, 0,
                         reason="Sum(...) вернул NULL, хотя суммируемое поле "
                                "не может быть NULL")
    return int(total)


def planned_by_block(*, project_id: int,
                     on: dt.date) -> dict[tuple[int, int | None], int]:
    """План по людям: ``{(block_id, work_role_id|None): Σ quantity}`` на дату.

    Берутся потребности РОУДМАПОВ проекта, действующие на дату ``on``
    (пустая граница = «без ограничения»). Потребности задач (``task``-ветка
    ``ResourceRequirement``) сюда НЕ входят намеренно — это детализация
    того же плана уровнем ниже, и сложение дало бы двойной счёт. То же
    правило и по той же причине, что в
    ``resource_service.roadmap_resource_totals``; разойтись этим двум
    местам нельзя.

    Одним запросом на всю выборку: конвенция ``_metrics_batch``.
    """
    rows = (ResourceRequirement.objects
            .filter(kind=ResourceKind.HUMAN,
                    roadmap__isnull=False,
                    roadmap__project_id=project_id,
                    roadmap__site_block_id__isnull=False)
            .filter(Q(start_date__isnull=True) | Q(start_date__lte=on))
            .filter(Q(end_date__isnull=True) | Q(end_date__gte=on))
            .values("roadmap__site_block_id", "work_role_id")
            .annotate(total=Sum("quantity")))
    return {(row["roadmap__site_block_id"], row["work_role_id"]):
            _group_total(row, site="tasks.staff_report.planned_null")
            for row in rows}


def daily_headcount_by_block(*, project_id: int,
                             on: dt.date) -> dict[int, int]:
    """``{block_id: Σ DailyReport.headcount}`` за дату — «сколько отчитались».

    Сверка, а не источник: ежедневка заполняется по задачам и headcount в
    ней необязателен, поэтому число здесь почти всегда меньше того, что
    заведено по объекту. Показывается рядом именно как расхождение.

    Задачи без блока в сумму не попадают: положить их некуда, а размазать
    по блокам значило бы выдумать данные.
    """
    rows = (DailyReport.objects
            .filter(is_deleted=False, task__is_deleted=False,
                    task__project_id=project_id, work_date=on,
                    headcount__isnull=False,
                    task__site_block_id__isnull=False)
            .values("task__site_block_id")
            .annotate(total=Sum("headcount")))
    return {row["task__site_block_id"]:
            _group_total(row, site="tasks.staff_report.daily_headcount_null")
            for row in rows}


def _comparison(planned: int | None, actual: int) -> tuple[int | None,
                                                           int | None]:
    """``(planned, delta)``. Без плана — ``None``, а не ``0``.

    Ровно как ``resource_service._comparison`` и по той же причине:
    нарисованный ноль читался бы как «расхождения нет».
    """
    if planned is None:
        return None, None
    return planned, actual - planned


def staff_board(*, project_id: int, on: dt.date) -> dict:
    """Доска численности проекта на дату: блок × (факт, план, ежедневка).

    Ради неё эндпоинт и существует: собирать это на фронте значило бы
    дёрнуть блоки, потом отчёт каждого, потом план каждого. Здесь один
    запрос на сущность — блоки, отчёты со строками, план, ежедневка,
    гидрация авторов.

    Строка есть у КАЖДОГО блока проекта, даже пустая: страница отвечает на
    вопрос «где ещё не отчитались», и блок без отчёта — самая нужная на ней
    строка.
    """
    site_ids = list(ProjectSite.objects.filter(project_id=project_id)
                    .values_list("site_id", flat=True))
    blocks = list(SiteBlock.objects.filter(site_id__in=site_ids)
                  .select_related("site")
                  .order_by("site__name", "order", "name"))
    if not blocks:
        return {"blocks": [], "total_actual": 0, "total_planned": None,
                "total_daily": 0}

    block_ids = [block.id for block in blocks]

    reports = list(ProjectStaffReport.objects
                   .filter(project_id=project_id, site_block_id__in=block_ids,
                           work_date=on, is_deleted=False)
                   .select_related("project", "site_block",
                                   "site_block__site")
                   .prefetch_related("lines__work_role"))
    by_block = {row.site_block_id: row for row in reports}

    planned = planned_by_block(project_id=project_id, on=on)
    daily = daily_headcount_by_block(project_id=project_id, on=on)

    role_names = dict(WorkRole.objects.values_list("id", "name"))

    rows: list[dict] = []
    for block in blocks:
        report = by_block.get(block.id)
        lines = list(report.lines.all()) if report else []
        actual_by_role = {line.work_role_id: line.headcount for line in lines}
        planned_by_role = {role_id: qty
                           for (blk, role_id), qty in planned.items()
                           if blk == block.id}

        role_ids = set(actual_by_role) | set(planned_by_role)
        roles = [{
            "work_role_id": role_id,
            "work_role_name": (role_names.get(role_id, "—") if role_id
                               is not None else UNSPECIFIED_ROLE_NAME),
            "planned": planned_by_role.get(role_id),
            "actual": actual_by_role.get(role_id, 0),
        } for role_id in role_ids]
        roles.sort(key=lambda row: row["work_role_name"])

        total_actual = sum(actual_by_role.values())
        # План блока — сумма ВСЕХ его потребностей, включая строку без
        # роли: она про людей и в «сколько нужно» входит.
        total_planned = (sum(planned_by_role.values())
                         if planned_by_role else None)
        total_planned, delta = _comparison(total_planned, total_actual)

        rows.append({
            "site_id": block.site_id,
            "site_name": block.site.name,
            "site_block_id": block.id,
            "site_block_name": block.name,
            "report_id": report.id if report else None,
            "total_headcount": total_actual,
            "planned_headcount": total_planned,
            "delta": delta,
            "daily_headcount": daily.get(block.id, 0),
            "comment": report.comment if report else "",
            "roles": roles,
        })

    planned_rows = [row["planned_headcount"] for row in rows
                    if row["planned_headcount"] is not None]
    return {
        "blocks": rows,
        "total_actual": sum(row["total_headcount"] for row in rows),
        "total_planned": sum(planned_rows) if planned_rows else None,
        "total_daily": sum(row["daily_headcount"] for row in rows),
    }


__all__ = [
    "REVISIONED_FIELDS", "UNSPECIFIED_ROLE_NAME",
    "get_report", "list_reports", "create_report", "update_report",
    "delete_report", "list_revisions",
    "build_report", "build_reports", "build_revisions",
    "planned_by_block", "daily_headcount_by_block", "staff_board",
]
