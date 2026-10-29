"""Бизнес-метрики тендерного модуля (T5.6; спека этапа 5, §3 T5.6).

Собирается по расписанию через ``apps.core.metrics``: ``tender`` —
тенантная аппка, ``collect()`` зовётся в схеме КАЖДОЙ компании, серии
получают метку ``company``. К соседям — только через их ``interface``.
``require_service`` здесь нет намеренно: наблюдаемость переживает
выключенный домен.

* ``tender_tenders{status}`` — тендеры по статусам. Справочная.
* ``tender_award_approval_stale`` — выборы «На утверждении» дольше
  ``STALE_WORKING_DAYS`` рабочих дней. Отсчёт — с активации ТЕКУЩЕГО этапа
  (``since`` из ``signoff.interface.current_holders``): выбор, который
  проверяющий качества держал неделю, а ФД получил вчера, у ФД не застрял.
  Без идущего процесса — с последнего изменения тендера. Рабочие дни — по
  производственному календарю (``refdata.working_days_between``), прошедшие
  ПОСЛЕ дня отсчёта. ``signoff`` или ``refdata`` выключены — метрики нет, а
  не ноль. Правило алертов — на неё (бизнес-чат).
* ``tender_delivery_overdue`` — поставщики «В поставке» (или «Принято
  частично»), у которых прошёл срок поставки из предложения: самая поздняя
  ``delivery_date`` выбранных строк, без запаса. Стадию считают документы
  БЗО — ``bpp`` выключен у компании, метрики нет. Справочная.
"""

from __future__ import annotations

from datetime import timedelta

from django.db import connection
from django.db.models import Count, Max
from django.utils import timezone

from apps.core.services import ServiceDisabled, service_enabled
from apps.refdata import interface as refdata
from apps.signoff import interface as signoff

from .models import Award, Tender, TenderStatus
from .services.delivery import stages

# «Дольше 3 рабочих дней» — спека этапа 5, §3 T5.6.
STALE_WORKING_DAYS = 3
#: Стадии, в которых поставщик везёт товар, — к ним и относится срок поставки.
SHIPPING = ("in_delivery", "partially_received")


def _table_exists(model) -> bool:
    """Таблица видна в схеме компании: до ``migrate_companies`` на выкатке
    выбора и приёмок ещё нет, и запрос уронил бы весь сбор модуля."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT to_regclass(current_schema() || '.' || %s)",
                       [model._meta.db_table])
        return cursor.fetchone()[0] is not None


def _by_status() -> dict:
    counts = dict(Tender.objects.values_list("status").annotate(n=Count("pk")))
    return {"tender_tenders": {
        "help": "Тендеры по статусам",
        "labels": ["status"],
        "values": [((status,), counts.get(status, 0)) for status in TenderStatus.values],
    }}


def _elapsed_working_days(since_day, today) -> int:
    """Рабочих дней прошло ПОСЛЕ дня отсчёта до сегодня включительно."""
    return refdata.working_days_between(since_day + timedelta(days=1), today) or 0


def _stale() -> dict:
    if not (service_enabled("signoff") and service_enabled("refdata")):
        return {}
    rows = list(Tender.objects.filter(status=TenderStatus.ON_APPROVAL)
                .values_list("pk", "updated_at"))
    try:
        holders = (signoff.current_holders(Tender.SIGNOFF_SUBJECT_TYPE, [pk for pk, _ in rows])
                   if rows else {})
        today = timezone.localdate()
        stale = sum(
            1 for pk, updated_at in rows
            if _elapsed_working_days(
                timezone.localtime(holders.get(str(pk), {}).get("since") or updated_at).date(),
                today) > STALE_WORKING_DAYS)
    except ServiceDisabled:
        return {}
    return {"tender_award_approval_stale": {
        "help": ("Выборы поставщиков на утверждении дольше %d рабочих дней"
                 % STALE_WORKING_DAYS),
        "values": [((), stale)],
    }}


def _overdue() -> dict:
    if not service_enabled("bpp"):
        return {}
    today = timezone.localdate()
    overdue = 0
    try:
        for tender in Tender.objects.filter(status__in=(TenderStatus.HANDED_OVER,
                                                        TenderStatus.DELIVERY)):
            due = {str(invitation): last for invitation, last in
                   Award.objects.filter(tender=tender, line__isnull=False)
                   .values_list("offer__invitation_id")
                   .annotate(last=Max("line__delivery_date"))}
            for row in stages.delivery_of(tender):
                last = due.get(row["invitation_id"])
                if row["stage"] in SHIPPING and last is not None and last < today:
                    overdue += 1
    except ServiceDisabled:
        return {}
    return {"tender_delivery_overdue": {
        "help": "Поставщики в поставке после срока поставки из предложения",
        "values": [((), overdue)],
    }}


def collect() -> dict:
    if not _table_exists(Tender):
        return {}
    result = _by_status()
    if _table_exists(Award):
        result.update(_stale())
        result.update(_overdue())
    return result
