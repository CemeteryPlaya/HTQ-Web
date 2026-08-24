"""Task-key generation and working-day deadline arithmetic.

**Key generation is the atomicity-critical path of this domain.** Two
concurrent creates must never produce the same ``TASK-N``. The original did
``SELECT ... FOR UPDATE`` on the counter row; this does the same with
``select_for_update()``, and the lock is only meaningful inside a
transaction — hence the explicit ``transaction.atomic()`` here rather than
relying on the caller. ``get_or_create`` handles the very first call: it
wraps its INSERT in a savepoint, so when two requests race to create the
counter the loser's unique-index violation is absorbed inside
``get_or_create`` and it returns the winner's row. Both then queue on
``select_for_update()`` and increment in turn.

Note the counter row is locked, not the ``tasks`` table — so key generation
serialises only against other key generations, not against the rest of the
create.
"""

from __future__ import annotations

from datetime import date, timedelta

from django.db import transaction

from ..models import ProductionDay, TaskSequence
from .production_calendar import WORKING_DAY_TYPES, base_day_type

# Потолок обхода в ``due_date_from_working_days``. Календарных дней на N
# рабочих нужно ~1.4·N (выходные) плюс праздники; тройной запас и месяц сверху
# покрывают любой реальный отрезок, но не дают циклу уйти в бесконечность,
# если оверрайды объявят рабочими нулевое количество дней.
_SCAN_FACTOR = 3
_SCAN_SLACK_DAYS = 30
# ~10 рабочих лет. Схема ``estimated_working_days`` — голый ``int | None``, а
# обход теперь идёт по дням, так что запрос с 10_000_000 крутил бы цикл
# впустую и упирался в переполнение ``date``. Прежняя версия была защищена
# двумя индексными запросами; эта защищается явным потолком.
_MAX_WORKING_DAYS = 2600

DEFAULT_PREFIX = "TASK"


def next_sequence_value(prefix: str = DEFAULT_PREFIX) -> int:
    """Atomically increment and return the next counter value for ``prefix``."""
    with transaction.atomic():
        # ``get_or_create`` already resolves the "two requests create the
        # first row at once" race on its own: it wraps the INSERT in a
        # savepoint and falls back to a SELECT when that INSERT hits the
        # unique index. Catching IntegrityError out here would be worse than
        # useless — it can never fire for that race, and for any OTHER
        # integrity failure the enclosing transaction is already poisoned, so
        # the next statement would raise TransactionManagementError and hide
        # the real cause behind a confusing one.
        TaskSequence.objects.get_or_create(name=prefix,
                                           defaults={"current_value": 0})
        row = TaskSequence.objects.select_for_update().get(name=prefix)
        row.current_value += 1
        row.save(update_fields=["current_value", "updated_at"])
        return row.current_value


def next_task_key(prefix: str = DEFAULT_PREFIX) -> str:
    """``TASK-17`` — the human-facing task identifier."""
    return f"{prefix}-{next_sequence_value(prefix)}"


def due_date_from_working_days(start_date: date, working_days: int) -> date | None:
    """The date that is ``working_days`` working days from ``start_date``.

    Inclusive of ``start_date`` itself when it is a working day — 1 working
    day starting Monday is Monday, not Tuesday (the original's ``+ working
    days - 1`` offset against the cumulative counter).

    Считается по СГЕНЕРИРОВАННОМУ календарю с оверрайдами поверх, а не по
    таблице ``ProductionDay`` — по той же причине, что и в
    ``calendar_service.working_days_between``: ``ProductionDay`` это таблица
    переопределений, а не календарь, и в обычной базе строк в ней нет вообще.
    Прежняя версия брала ``working_days_since_epoch`` из строки за
    ``start_date`` и без неё возвращала ``None`` — то есть на любой не
    размеченной вручную базе ``estimated_working_days`` при создании задачи
    молча терялся. Заодно снимается ограничение «отрезок не пересекает
    1 января»: счётчик там сбрасывается, а обход по дням — нет.

    ``None`` — если ``working_days`` не положительное, выходит за
    ``_MAX_WORKING_DAYS`` или рабочих дней не набралось в пределах потолка
    обхода. Вызывающий трактует это как «дедлайн не вычислен» и оставляет
    ``due_date``, присланный клиентом.
    """
    if working_days is None or not 1 <= working_days <= _MAX_WORKING_DAYS:
        return None
    limit = start_date + timedelta(
        days=working_days * _SCAN_FACTOR + _SCAN_SLACK_DAYS)
    overrides = dict(ProductionDay.objects
                     .filter(date__gte=start_date, date__lte=limit)
                     .values_list("date", "day_type"))
    seen = 0
    day = start_date
    while day <= limit:
        day_type = overrides.get(day) or base_day_type(day)
        if day_type in WORKING_DAY_TYPES:
            seen += 1
            if seen == working_days:
                return day
        day += timedelta(days=1)
    return None
