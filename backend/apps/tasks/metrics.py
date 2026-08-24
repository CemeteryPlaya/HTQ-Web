"""Бизнес-метрики домена задач.

Собирается ``apps.core.metrics.collect_all`` по расписанию (Celery-beat),
не на скрейпе — см. докстринг там. Обращается ТОЛЬКО к своим моделям:
кросс-доменные импорты запрещены (``apps/core/tests/test_app_isolation.py``),
и именно поэтому метрики живут в аппке, а не в общем сборщике.
"""
from __future__ import annotations

import datetime as dt

from django.db.models import Count
from django.utils import timezone

from .models import TERMINAL_STATUSES, DailyReport, Project, Task


def collect() -> dict:
    today = timezone.localdate()

    by_status = (Task.objects.filter(is_deleted=False)
                 .values("status").annotate(n=Count("id")))

    # Просрочка — то, ради чего вообще смотрят на задачи со стороны
    # руководства: срок прошёл, а работа не закрыта.
    overdue = (Task.objects
               .filter(is_deleted=False, due_date__lt=today)
               .exclude(status__in=TERMINAL_STATUSES)
               .count())

    # Отчитались ли сегодня по объектам. Ноль в рабочий день означает, что
    # либо встали работы, либо перестали заполнять — и то и другое
    # заслуживает вопроса.
    reports_today = DailyReport.objects.filter(
        work_date=today, is_deleted=False).count()

    # Отставание ввода: с какой давности лежит самый свежий отчёт.
    latest = (DailyReport.objects.filter(is_deleted=False)
              .order_by("-work_date").values_list("work_date", flat=True)
              .first())
    staleness = (today - latest).days if latest else None

    result = {
        # Без суффикса _total намеренно: это gauge (сколько задач в статусе
        # ПРЯМО СЕЙЧАС), а _total по конвенции Prometheus означает монотонный
        # счётчик — к такому имени рано или поздно применят rate() и получат
        # бессмыслицу.
        "tasks": {
            "help": "Задачи по статусам",
            "labels": ["status"],
            "values": [((row["status"],), row["n"]) for row in by_status],
        },
        "tasks_overdue": {
            "help": "Незакрытые задачи с истёкшим сроком",
            "values": [((), overdue)],
        },
        "projects_active": {
            "help": "Проекты в работе",
            "values": [((), Project.objects.filter(status="active").count())],
        },
        "daily_reports_today": {
            "help": "Ежедневных отчётов по выработке за сегодня",
            "values": [((), reports_today)],
        },
    }

    # None не экспортируем: «отчётов не было никогда» и «последний был
    # сегодня» — разные вещи, а нулём они выглядели бы одинаково.
    if staleness is not None:
        result["daily_report_staleness_days"] = {
            "help": "Дней с даты самого свежего ежедневного отчёта",
            "values": [((), staleness)],
        }
    return result
