"""Бизнес-метрики модуля БЗО (задача A3.2, части 1 и 2).

Собирается по расписанию через ``apps.core.metrics`` — см. докстринг там:
``bpp`` — тенантная аппка, поэтому ``collect()`` зовётся в схеме КАЖДОЙ
компании, а серии получают метку ``company``. Обращается только к своим
моделям и к соседям через их ``interface`` (правило изоляции аппок).
``require_service`` здесь нет намеренно: наблюдаемость переживает
выключенный домен.

Метрики:

* ``bpp_requests_in_approval`` — заявки «На согласовании». Справочная, порога
  нет.
* ``bpp_requests_in_approval_stale`` — из них стоят дольше
  ``STALE_WORKING_DAYS`` рабочих дней. Отсчёт — с активации ТЕКУЩЕГО этапа
  (``since`` из ``signoff.interface.current_holders``): заявка, которую ТД
  держал неделю, а ОД получил вчера, у ОД не застряла. У заявки без идущего
  процесса (статус и согласование разошлись) отсчёт — с последнего изменения
  заявки: такая заявка не сдвинется никогда. Рабочие дни — Пн–Пт без
  праздников: производственный календарь живёт в ``hr`` без функции
  интерфейса, а метрика не алертится (шапка ``rules.yml``) — на сдвиг на
  праздник её точности хватает. ``signoff`` выключен — метрики нет вовсе, а
  не ноль: «не из чего считать» и «ничего не застряло» — разное.
* ``bpp_committed_mismatches`` и ``bpp_committed_check_age_seconds`` — итог
  последней ночной сверки «Задействовано» (D-S3-4): сверку не пересчитываем
  каждую минуту, её пишет ``services/budget/check.run`` в настройку модуля
  ``committed_check_last``. Итога нет (сверка в компании не бежала ни разу) —
  обеих метрик нет: пустое ≠ ноль. ``bpp`` выключен у компании — тоже нет:
  ночная задача там не идёт (``require_service`` в ней), и возраст рос бы до
  ложного «сверка встала», а число расхождений висело бы устаревшим.
* ``bpp_bank_imports_failed`` — загрузки выписок в «Ошибка загрузки» за
  ``FAILED_IMPORTS_DAYS`` дней. Справочная: автор загрузки видит ошибку на
  экране сразу, алерт не нужен.
* ``bpp_invoices_awaiting_fd`` — счета «На рассмотрении ФД», очередь ФД
  (вкладка реестра «На решение ФД»). Справочная: решение ФД — задача
  ``signoff``, и её адресно показывает ежедневная сводка «ждут вашего
  решения».
* ``bpp_invoices_to_pay`` — очередь БУХ: «К оплате» И «Оплачено частично» —
  ровно вкладка реестра «К оплате» (``services/invoices/read.py::TABS``).
  Частично оплаченный счёт ещё ждёт бухгалтера — остаток платит он же, и
  вне очереди такой счёт выпал бы из обеих цифр. Справочная.
* ``bpp_invoices_closing_docs_overdue`` — «Ждёт закрывающих документов»
  дольше ``CLOSING_DOCS_OVERDUE_DAYS`` дней (Q-C29, D-13). Дни КАЛЕНДАРНЫЕ и
  по дате в поясе TIME_ZONE — те же «N дн.», что карточка счёта и раздел сводки
  автора (``services/invoices/payments.py::closing_docs_pending_for_user``):
  метрика и экран не должны расходиться в счёте. Отсчёт — с запроса
  документов ``docs_requested_at``; возврат документов на доработку его не
  сбрасывает — ждём тех же документов. Бизнес-правило в отдельном чате.

Технические строки переноса из ``contracts`` (``is_migrated``) не входят ни
в одну метрику — их не показывают и реестры модуля.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta

from django.db import connection
from django.db.models import Count, Q
from django.db.models.functions import Coalesce
from django.utils import timezone

from apps.core.services import ServiceDisabled, service_enabled
from apps.signoff import interface as signoff

from .models.bank import BankImport, BankImportStatus
from .models.invoices import Invoice, InvoiceStatus
from .models.requests import PurchaseRequest, RequestStatus
from .services.budget.check import RESULT_KEY
from .services.core.settings import get_setting

# «Дольше 5 рабочих дней» — срок из плана этапа 3 (A3.2).
STALE_WORKING_DAYS = 5
# Окно «загрузки с ошибкой»: неделя — с запасом на выходные, не больше, чтобы
# старая починенная ошибка не висела на панели месяц.
FAILED_IMPORTS_DAYS = 7
# «Ждёт закрывающих дольше 5 дней» — Q-C29, мастер-план A3.2.
CLOSING_DOCS_OVERDUE_DAYS = 5


def _stale_before(now: datetime) -> datetime:
    """Начало дня, отстоящего от сегодня на ``STALE_WORKING_DAYS`` рабочих.

    Счёт по дням, а не по часам: заявка, отправленная в понедельник,
    становится застрявшей со вторника следующей недели — прошли пять полных
    рабочих дней (Вт–Пт и Пн), и идёт шестой.
    """
    day = timezone.localdate(now)
    left = STALE_WORKING_DAYS
    while left:
        day -= timedelta(days=1)
        if day.weekday() < 5:
            left -= 1
    return timezone.make_aware(datetime.combine(day, time.min))


def _requests(now: datetime) -> dict:
    # Техническая заявка переноса из contracts (Q-D06) в статистику не входит.
    rows = list(PurchaseRequest.objects
                .filter(status=RequestStatus.IN_APPROVAL, is_migrated=False)
                .values_list("pk", "updated_at"))
    result = {
        "bpp_requests_in_approval": {
            "help": "Заявки на закупку «На согласовании»",
            "values": [((), len(rows))],
        },
    }
    # Согласование выключено у компании — «зависших» не считаем вовсе, а не
    # отдаём 0: пустая очередь и «не знаем» не должны выглядеть одинаково.
    # ``current_holders`` читает ещё и должности ``hr`` — выключенный ``hr``
    # тоже убирает метрику (ServiceDisabled ниже).
    if not service_enabled("signoff"):
        return result
    try:
        holders = (signoff.current_holders(PurchaseRequest.SIGNOFF_SUBJECT_TYPE,
                                           [pk for pk, _ in rows]) if rows else {})
    except ServiceDisabled:
        return result
    cutoff = _stale_before(now)
    stale = sum(1 for pk, updated_at in rows
                if (holders.get(str(pk), {}).get("since") or updated_at) < cutoff)
    result["bpp_requests_in_approval_stale"] = {
        "help": ("Заявки на закупку на текущем этапе согласования дольше %d "
                 "рабочих дней" % STALE_WORKING_DAYS),
        "values": [((), stale)],
    }
    return result


def _committed_check(now: datetime) -> dict:
    last = get_setting(RESULT_KEY)
    if not last:
        return {}
    # Строку можно поправить руками в django-admin (``ModuleSettingAdmin``):
    # битое значение гасит только метрики сверки, а не весь сбор компании.
    try:
        at = datetime.fromisoformat(last["at"])
        count = int(last["count"])
    except (KeyError, TypeError, ValueError):
        return {}
    return {
        "bpp_committed_mismatches": {
            "help": "Расхождения «Задействовано» в последней ночной сверке",
            "values": [((), count)],
        },
        "bpp_committed_check_age_seconds": {
            "help": "Секунд с последней ночной сверки «Задействовано»",
            "values": [((), (now - at).total_seconds())],
        },
    }


def _table_exists(model) -> bool:
    """Таблица модели видна в ``search_path`` компании.

    Загрузки выписок пришли на этапе 3; до ``migrate_companies`` на выкатке
    их таблицы в схеме компании ещё нет. Без проверки запрос упал бы, и
    сборщик потерял бы у компании ВСЕ метрики модуля, включая сверку денег.
    """
    with connection.cursor() as cursor:
        # Только в схеме компании: ``search_path`` включает и ``public``, и
        # таблица, оставшаяся там, иначе подменила бы отсутствующую.
        cursor.execute("SELECT to_regclass(current_schema() || '.' || %s)",
                       [model._meta.db_table])
        return cursor.fetchone()[0] is not None


def _bank(now: datetime) -> dict:
    if not _table_exists(BankImport):
        return {}
    failed = (BankImport.objects
              .filter(status=BankImportStatus.FAILED,
                      created_at__gte=now - timedelta(days=FAILED_IMPORTS_DAYS))
              .count())
    return {
        "bpp_bank_imports_failed": {
            "help": ("Загрузки выписок «Ошибка загрузки» за %d дней"
                     % FAILED_IMPORTS_DAYS),
            "values": [((), failed)],
        },
    }


def _docs_overdue_before(now: datetime) -> datetime:
    """Начало местного дня, отстоящего от сегодня на
    ``CLOSING_DOCS_OVERDUE_DAYS`` календарных.

    Запрос раньше этой границы — прошло больше пяти дней по счёту карточки
    («ждёт закрывающих 6 дн.»); запрос ровно пять дней назад, в любое время
    суток, — ещё нет.
    """
    day = timezone.localdate(now) - timedelta(days=CLOSING_DOCS_OVERDUE_DAYS)
    return timezone.make_aware(datetime.combine(day, time.min))


def _invoices(now: datetime) -> dict:
    # Счета — этап 3; до ``migrate_companies`` на выкатке таблицы нет (см.
    # ``_table_exists``).
    if not _table_exists(Invoice):
        return {}
    # Без даты запроса «Ждёт закрывающих» не бывает штатно (её ставит
    # ``request_docs``); строку, поправленную руками, считаем от последнего
    # изменения, чтобы она не пропала из счёта навсегда.
    counts = (Invoice.objects.filter(is_migrated=False)
              .annotate(docs_since=Coalesce("docs_requested_at", "updated_at"))
              .aggregate(
                  fd=Count("pk", filter=Q(status=InvoiceStatus.UNDER_REVIEW)),
                  to_pay=Count("pk", filter=Q(status__in=[InvoiceStatus.TO_PAY,
                                                          InvoiceStatus.PARTIALLY_PAID])),
                  overdue=Count("pk", filter=Q(status=InvoiceStatus.AWAITING_DOCS,
                                               docs_since__lt=_docs_overdue_before(now))),
              ))
    return {
        "bpp_invoices_awaiting_fd": {
            "help": "Счета «На рассмотрении ФД» — очередь финансового директора",
            "values": [((), counts["fd"])],
        },
        "bpp_invoices_to_pay": {
            "help": "Счета «К оплате» и «Оплачено частично» — очередь бухгалтера",
            "values": [((), counts["to_pay"])],
        },
        "bpp_invoices_closing_docs_overdue": {
            "help": ("Счета «Ждёт закрывающих документов» дольше %d календарных дней"
                     % CLOSING_DOCS_OVERDUE_DAYS),
            "values": [((), counts["overdue"])],
        },
    }


def collect() -> dict:
    now = timezone.now()
    result = _requests(now)
    if service_enabled("bpp"):
        result.update(_committed_check(now))
    result.update(_bank(now))
    # Счета выключены у компании — очередей нет и действовать некому (экран
    # отвечает 503): метрики не отдаём, иначе правило о закрывающих горело бы
    # неделями, а сводка (bpp/digest.py) у этой компании при этом молчит.
    if service_enabled("bpp_invoices"):
        result.update(_invoices(now))
    return result
