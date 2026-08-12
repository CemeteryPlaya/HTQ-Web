"""Task-key generation — the atomicity-critical path of the domain.

Found during the phase-4 final review: ``next_sequence_value`` used to wrap
``get_or_create`` in ``try/except IntegrityError: pass`` inside the atomic
block. That handler could never fire for the race it claimed to cover
(``get_or_create`` absorbs it in its own savepoint) and, for any other
integrity failure, would have left the transaction poisoned so the next
statement raised ``TransactionManagementError`` instead of the real cause.
These tests pin the behaviour the fix relies on.
"""

import datetime

import pytest
from django.db import IntegrityError, transaction
from django.db.transaction import TransactionManagementError

from apps.tasks.models import ProductionDay, Task, TaskSequence
from apps.tasks.services import sequence_service


@pytest.mark.django_db
def test_first_call_creates_the_counter():
    assert sequence_service.next_task_key() == "TASK-1"
    assert TaskSequence.objects.get(name="TASK").current_value == 1


@pytest.mark.django_db
def test_values_are_strictly_increasing():
    keys = [sequence_service.next_task_key() for _ in range(5)]
    assert keys == [f"TASK-{i}" for i in range(1, 6)]


@pytest.mark.django_db
def test_prefixes_have_independent_counters():
    sequence_service.next_task_key("TASK")
    assert sequence_service.next_task_key("OPS") == "OPS-1"
    assert sequence_service.next_task_key("TASK") == "TASK-2"


@pytest.mark.django_db
def test_generation_works_inside_a_caller_transaction():
    """``create_task`` is itself atomic, so this nests. The inner atomic must
    behave as a savepoint, not fail."""
    with transaction.atomic():
        assert sequence_service.next_task_key() == "TASK-1"
        Task.objects.create(key="TASK-1", summary="S")
    assert Task.objects.filter(key="TASK-1").exists()


@pytest.mark.django_db(transaction=True)
def test_get_or_create_absorbs_the_create_race_by_itself():
    """The reason the removed IntegrityError handler was dead code: a losing
    INSERT is caught inside ``get_or_create``'s own savepoint and the
    surrounding transaction stays usable."""
    TaskSequence.objects.create(name="RACE", current_value=5)
    with transaction.atomic():
        row, created = TaskSequence.objects.get_or_create(
            name="RACE", defaults={"current_value": 0})
        assert created is False and row.current_value == 5
        # The transaction is still alive — this is what a hand-rolled
        # except-IntegrityError would have destroyed.
        assert TaskSequence.objects.filter(name="RACE").exists()


@pytest.mark.django_db(transaction=True)
def test_swallowing_an_integrity_error_would_poison_the_transaction():
    """Pins WHY the handler had to go: catching IntegrityError and carrying on
    inside the same atomic block turns any further query into an opaque
    TransactionManagementError."""
    TaskSequence.objects.create(name="X", current_value=0)
    with pytest.raises(TransactionManagementError):
        with transaction.atomic():
            try:
                TaskSequence.objects.create(name="X")   # unique violation
            except IntegrityError:
                pass
            TaskSequence.objects.get(name="X")


@pytest.mark.django_db
def test_counter_survives_a_concurrent_style_interleave():
    """Two sequential generations against a pre-existing row — the common
    production path once the counter exists."""
    TaskSequence.objects.create(name="TASK", current_value=41)
    assert sequence_service.next_task_key() == "TASK-42"
    assert sequence_service.next_task_key() == "TASK-43"


# ── дедлайн по рабочим дням ─────────────────────────────────────────────

@pytest.mark.django_db
def test_due_date_is_computed_without_any_stored_calendar_row():
    """Регрессия: функция читала ``working_days_since_epoch`` из
    ``ProductionDay``, а это таблица переопределений — на обычной базе она
    пуста, и ``estimated_working_days`` при создании задачи молча терялся."""
    assert ProductionDay.objects.count() == 0
    # 5 января 2026 — понедельник, первый рабочий день года, и он же первый из
    # пяти. Дальше 6-е, Рождество 7-го мимо, 8-е, 9-е — пятый выпадает на
    # понедельник 12 января.
    due = sequence_service.due_date_from_working_days(datetime.date(2026, 1, 5), 5)
    assert due == datetime.date(2026, 1, 12)


@pytest.mark.django_db
def test_due_date_skips_weekends_and_holidays():
    # От четверга 1 января (праздник): рабочие — 5, 6, 8 (7-е Рождество), 9.
    due = sequence_service.due_date_from_working_days(datetime.date(2026, 1, 1), 4)
    assert due == datetime.date(2026, 1, 9)


@pytest.mark.django_db
def test_due_date_crosses_the_new_year():
    """Счётчик ``working_days_since_epoch`` сбрасывается 1 января, поэтому
    прежняя реализация на таком отрезке не работала в принципе."""
    due = sequence_service.due_date_from_working_days(datetime.date(2026, 12, 28), 5)
    assert due == datetime.date(2027, 1, 5)


@pytest.mark.django_db
def test_stored_override_wins_over_the_generated_day():
    ProductionDay.objects.create(date=datetime.date(2026, 1, 6),
                                 day_type="holiday", working_days_since_epoch=0)
    due = sequence_service.due_date_from_working_days(datetime.date(2026, 1, 5), 2)
    assert due == datetime.date(2026, 1, 8)


@pytest.mark.django_db
def test_non_positive_working_days_has_no_deadline():
    assert sequence_service.due_date_from_working_days(datetime.date(2026, 1, 5), 0) is None
    assert sequence_service.due_date_from_working_days(datetime.date(2026, 1, 5), None) is None


@pytest.mark.django_db
def test_absurd_working_days_is_rejected_before_the_scan():
    """``estimated_working_days`` в схеме — голый ``int``, а обход идёт по
    дням: без потолка запрос уронил бы воркер переполнением ``date``."""
    assert sequence_service.due_date_from_working_days(
        datetime.date(2026, 1, 5), 10_000_000) is None
