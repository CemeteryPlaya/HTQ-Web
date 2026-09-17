"""Сводка домена работ по всей группе.

Считается агрегатами в БД, а не обходом компаний в Python: ради этого
платформа и выбрала UNION ALL-представления вместо склейки в памяти
(докстринг apps/companies/services/holding_views.py).
"""

from __future__ import annotations

from django.db import ProgrammingError, connection
from django.db.models import Count, Max, Q
from django.utils import timezone

from htqweb.tenancy.context import HOLDING_SCHEMA
from htqweb.tenancy.db import use_holding

from ..holding_models import (
    HoldingDailyReport, HoldingProject, HoldingSite, HoldingTask,
)
from ..models import TERMINAL_STATUSES, ProjectStatus, SiteStatus


class HoldingViewsUnavailable(RuntimeError):
    """Представлений холдинга сейчас не существует.

    Состояние штатное, а не аварийное: ``migrate_companies`` сносит их на
    время прогона миграций. Вьюха обязана перевести это в 503 «сводки
    пересобираются» — нули на экране директор примет за правду.
    """


def _views_are_gone() -> bool:
    """Правда ли, что вьюх нет, — спрашивается ТОЛЬКО на ветке ошибки.

    ``ProgrammingError`` ловится широко (psycopg поднимает его и на опечатке
    в SQL), поэтому причина уточняется отдельным запросом: иначе настоящая
    ошибка запроса маскировалась бы под «идёт выкатка». ATOMIC_REQUESTS в
    проекте выключен, поэтому упавший запрос не отравляет соединение и
    второй запрос проходит. По той же причине вызывающий НЕ должен
    оборачивать сводку в ``transaction.atomic()``: внутри явной транзакции
    этот второй запрос дал бы ``TransactionManagementError`` вместо
    внятного 503.
    """
    with connection.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM information_schema.views WHERE table_schema = %s",
            [HOLDING_SCHEMA],
        )
        (count,) = cur.fetchone()
    return count == 0


def _by_company(queryset, **aggregates) -> dict[str, dict]:
    grouped = queryset.values("company_slug").annotate(**aggregates)
    return {row.pop("company_slug"): row for row in grouped}


def projects_by_company() -> list[dict]:
    """По строке на действующую компанию: проекты, объекты, задачи, отчёты.

    Определения цифр — экран и API обязаны говорить одно и то же:

    * ``projects_active`` — проекты со ``status="active"``
      (``ProjectStatus.ACTIVE``); завершённые и архивные не считаются;
    * ``sites_active`` — объекты со ``status="active"`` (``SiteStatus.ACTIVE``);
      приостановленные и закрытые не считаются;
    * ``tasks_open`` — задачи с ``is_deleted=False`` и статусом НЕ в
      ``TERMINAL_STATUSES`` (``"done"``, ``"cancelled"``);
    * ``tasks_overdue`` — открытые (по определению выше) с ``due_date`` СТРОГО
      раньше сегодняшнего дня: срок «сегодня» ещё не просрочен, задача без
      срока просроченной не бывает, закрытая — тем более;
    * ``reports_last_date`` — ``Max("work_date")`` по неудалённым ежедневным
      отчётам (``datetime.date``); ``None`` у компании без отчётов, и это
      НЕ ноль и не сегодняшняя дата — «не отчитывались никогда» и
      «отчитались сегодня» обязаны различаться.

    «Сегодня» — ``django.utils.timezone.localdate()``, а не
    ``datetime.date.today()``: платформа живёт в UTC, хост — не обязательно,
    и на этом расхождении в ``apps/tasks`` уже падали чужие тесты.

    Условия по статусу стоят внутри ``Count(filter=...)``, а не в
    ``filter()`` выборки, намеренно: компания, у которой все проекты
    архивные или все задачи закрыты, обязана остаться строкой сводки с
    нулём, а не исчезнуть. Мягко удалённые строки, напротив, отсекаются
    выборкой — их как бы нет. Компания, у которой нет ни одного проекта,
    объекта, задачи и отчёта, в сводке не появится вовсе: список слагов
    собирается из представлений, а не из реестра (принято как наблюдение,
    так же, как в домене кадров).

    Архивных компаний в представлениях нет по построению
    (``rebuild_holding_views`` читает только действующие) — поэтому фильтра
    по статусу компании здесь нет и быть не должно.
    """
    today = timezone.localdate()
    is_open = ~Q(status__in=TERMINAL_STATUSES)
    try:
        with use_holding():
            projects = _by_company(
                HoldingProject.objects.all(),
                projects_active=Count("id", filter=Q(status=ProjectStatus.ACTIVE)),
            )
            sites = _by_company(
                HoldingSite.objects.all(),
                sites_active=Count("id", filter=Q(status=SiteStatus.ACTIVE)),
            )
            tasks = _by_company(
                HoldingTask.objects.filter(is_deleted=False),
                tasks_open=Count("id", filter=is_open),
                tasks_overdue=Count("id", filter=is_open & Q(due_date__lt=today)),
            )
            reports = _by_company(
                HoldingDailyReport.objects.filter(is_deleted=False),
                reports_last_date=Max("work_date"),
            )
    except ProgrammingError:
        if _views_are_gone():
            raise HoldingViewsUnavailable(
                "Сводные представления холдинга сейчас пересобираются"
            ) from None
        raise

    slugs = sorted(set(projects) | set(sites) | set(tasks) | set(reports))
    return [
        {
            "company_slug": slug,
            # int(...) явно: Count и так отдаёт int, но приведение делается
            # ЗДЕСЬ, чтобы у вьюхи не было своей версии правды о типах.
            "projects_active": int(projects.get(slug, {}).get("projects_active") or 0),
            "sites_active": int(sites.get(slug, {}).get("sites_active") or 0),
            "tasks_open": int(tasks.get(slug, {}).get("tasks_open") or 0),
            "tasks_overdue": int(tasks.get(slug, {}).get("tasks_overdue") or 0),
            # Дата остаётся datetime.date (или None): в JSON её переводит
            # схема ручки (pydantic, mode="json"), а не сервис.
            "reports_last_date": reports.get(slug, {}).get("reports_last_date"),
        }
        for slug in slugs
    ]
