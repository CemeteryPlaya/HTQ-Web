"""Бизнес-метрики модуля БЗО (задача A3.2, часть 1).

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
"""

from __future__ import annotations

from datetime import datetime, time, timedelta

from django.db import connection
from django.utils import timezone

from apps.core.services import ServiceDisabled, service_enabled
from apps.signoff import interface as signoff

from .models.bank import BankImport, BankImportStatus
from .models.requests import PurchaseRequest, RequestStatus
from .services.budget.check import RESULT_KEY
from .services.core.settings import get_setting

# «Дольше 5 рабочих дней» — срок из плана этапа 3 (A3.2).
STALE_WORKING_DAYS = 5
# Окно «загрузки с ошибкой»: неделя — с запасом на выходные, не больше, чтобы
# старая починенная ошибка не висела на панели месяц.
FAILED_IMPORTS_DAYS = 7


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


def collect() -> dict:
    now = timezone.now()
    result = _requests(now)
    if service_enabled("bpp"):
        result.update(_committed_check(now))
    result.update(_bank(now))
    return result
