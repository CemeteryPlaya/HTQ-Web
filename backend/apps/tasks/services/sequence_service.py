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

from datetime import date

from django.db import transaction

from ..models import ProductionDay, TaskSequence
from .production_calendar import WORKING_DAY_TYPES

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

    Returns ``None`` when the production calendar has no row for
    ``start_date`` or does not extend far enough. That is the original's
    behaviour and the caller treats it as "no computed deadline", falling
    back to whatever ``due_date`` the client sent.
    """
    if working_days is None or working_days < 1:
        return None
    anchor = (ProductionDay.objects
              .filter(date=start_date)
              .values_list("working_days_since_epoch", flat=True)
              .first())
    if anchor is None:
        return None
    target = anchor + working_days - 1
    return (ProductionDay.objects
            .filter(date__gte=start_date,
                    day_type__in=WORKING_DAY_TYPES,
                    working_days_since_epoch__gte=target)
            .order_by("date")
            .values_list("date", flat=True)
            .first())
