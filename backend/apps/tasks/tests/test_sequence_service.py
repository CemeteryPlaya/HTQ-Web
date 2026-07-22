"""Task-key generation — the atomicity-critical path of the domain.

Found during the phase-4 final review: ``next_sequence_value`` used to wrap
``get_or_create`` in ``try/except IntegrityError: pass`` inside the atomic
block. That handler could never fire for the race it claimed to cover
(``get_or_create`` absorbs it in its own savepoint) and, for any other
integrity failure, would have left the transaction poisoned so the next
statement raised ``TransactionManagementError`` instead of the real cause.
These tests pin the behaviour the fix relies on.
"""

import pytest
from django.db import IntegrityError, transaction
from django.db.transaction import TransactionManagementError

from apps.tasks.models import Task, TaskSequence
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
