"""Бизнес-метрики согласований.

Собирается по расписанию через ``apps.core.metrics`` — см. докстринг там.
Обращается только к своим моделям (правило изоляции аппок).
"""
from __future__ import annotations

import datetime as dt

from django.db.models import Count
from django.utils import timezone

from .models import RequestInstance, RequestStatus


def collect() -> dict:
    by_status = RequestInstance.objects.values("status").annotate(n=Count("id"))

    # Застрявшие: на согласовании дольше недели. Главный предметный вопрос
    # к этому домену — не «сколько заявок», а «сколько из них никто не
    # двигает». Считаем по updated_at: заявка, которую вчера вернули на
    # доработку, застрявшей не является.
    stuck_since = timezone.now() - dt.timedelta(days=7)
    stuck = RequestInstance.objects.filter(
        status=RequestStatus.PENDING, updated_at__lt=stuck_since).count()

    return {
        # Без суффикса _total: это gauge текущего распределения по статусам,
        # а не монотонный счётчик (см. тот же комментарий в apps/tasks).
        "requests": {
            "help": "Заявки на согласование по статусам",
            "labels": ["status"],
            "values": [((row["status"],), row["n"]) for row in by_status],
        },
        "requests_stuck": {
            "help": "Заявки на согласовании без движения дольше 7 дней",
            "values": [((), stuck)],
        },
    }
