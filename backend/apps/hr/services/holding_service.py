"""Сводка домена кадров по всей группе.

Считается агрегатами в БД, а не обходом компаний в Python: ради этого
платформа и выбрала UNION ALL-представления вместо склейки в памяти
(докстринг apps/companies/services/holding_views.py).
"""

from __future__ import annotations

from django.db import ProgrammingError, connection
from django.db.models import Count, DecimalField, F, Q, Sum

from htqweb.tenancy.context import HOLDING_SCHEMA
from htqweb.tenancy.db import use_holding

from ..holding_models import (
    HoldingDepartment, HoldingEmployee, HoldingPosition, HoldingStaffingPosition,
)
from ..models import EmployeeStatus


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
    второй запрос проходит.
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


def headcount_by_company() -> list[dict]:
    """По строке на действующую компанию: люди, структура, штат.

    ``staffing_payroll_fund`` — ФОНД оплаты труда, ``Sum(headcount * salary)``
    по каждой строке штатного расписания, а НЕ сумма окладов
    (``Sum(salary)``). Домен уже определяет ФОТ этой формулой в двух местах,
    и обе — источник правды, с которым сводка обязана совпасть на глаз у
    директора: ``staffing_service.py::payroll_summary`` (строка
    ``fot = (line.headcount or 0) * (line.salary or 0)``, ручка
    ``payroll_summary`` уже в проде) и ``approval_hooks.py::_staffing_facts``
    (``"payroll": line.salary * line.headcount``, с тем же комментарием —
    ФОТ считается по строке целиком, а не по окладу одного человека).
    Сумма окладов без учёта штатных единиц — другая величина, у которой в
    этом домене нет отдельного названия и отдельной ручки.

    Условия по активности (``status``/``is_active``) стоят внутри
    ``Count(filter=...)``, а не в ``filter()`` выборки, намеренно —
    приём, как в ``apps.tasks.services.holding_service.projects_by_company``:
    компания, у которой ВСЕ отделы/должности архивны (или сотрудников нет
    вовсе), обязана остаться строкой сводки с нулём, а не исчезнуть.
    Мягко удалённые строки (``employees``), напротив, отсекаются самой
    выборкой — их как бы нет; у отделов и должностей мягкого удаления нет,
    поэтому для них ``.objects.all()``.

    Архивных компаний в представлениях нет по построению
    (``rebuild_holding_views`` читает только действующие) — поэтому фильтра
    по статусу компании здесь нет и быть не должно.
    """
    try:
        with use_holding():
            people = _by_company(
                HoldingEmployee.objects.filter(is_deleted=False),
                employees_total=Count("id"),
                employees_active=Count("id", filter=Q(status=EmployeeStatus.ACTIVE)),
            )
            departments = _by_company(
                HoldingDepartment.objects.all(),
                departments_active=Count("id", filter=Q(is_active=True)),
            )
            positions = _by_company(
                HoldingPosition.objects.all(),
                positions_active=Count("id", filter=Q(is_active=True)),
            )
            staffing = _by_company(
                HoldingStaffingPosition.objects.all(),
                staffing_headcount=Sum("headcount"),
                staffing_payroll_fund=Sum(
                    F("headcount") * F("salary"),
                    output_field=DecimalField(max_digits=17, decimal_places=2),
                ),
            )
    except ProgrammingError:
        if _views_are_gone():
            raise HoldingViewsUnavailable(
                "Сводные представления холдинга сейчас пересобираются"
            ) from None
        raise

    slugs = sorted(set(people) | set(departments) | set(positions) | set(staffing))
    return [
        {
            "company_slug": slug,
            "employees_active": int(people.get(slug, {}).get("employees_active") or 0),
            "employees_total": int(people.get(slug, {}).get("employees_total") or 0),
            "departments_active": int(
                departments.get(slug, {}).get("departments_active") or 0),
            "positions_active": int(
                positions.get(slug, {}).get("positions_active") or 0),
            # float, а не Decimal: JsonResponse Decimal не сериализует, а
            # схема ручки объявляет float. Приведение делается ЗДЕСЬ, чтобы у
            # вьюхи не было своей версии правды о типах.
            "staffing_headcount": float(
                staffing.get(slug, {}).get("staffing_headcount") or 0),
            "staffing_payroll_fund": float(
                staffing.get(slug, {}).get("staffing_payroll_fund") or 0),
        }
        for slug in slugs
    ]
