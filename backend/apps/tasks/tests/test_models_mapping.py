"""Model-level checks for the ported ``tasks`` schema.

Guards the three decisions that a careless later edit would quietly undo:
Django owns the schema (``managed=True``, idiomatic table names), the two
replica tables are gone for good (Р2), and the FSM table is byte-identical
to the FastAPI original it was copied from.
"""

import pytest
from django.db import connection
from django.db import models as dj_models

from apps.tasks import models

ALL_MODELS = (
    models.Task, models.TaskType, models.Project, models.Label,
    models.Equipment, models.TaskDepartmentLink, models.TaskAssignee,
    models.TaskDelegate, models.TaskWatcher, models.TaskComment,
    models.TaskAttachment, models.TaskActivity, models.TaskLink,
    models.TaskAssignment, models.Notification, models.TaskSequence,
    models.ProductionDay, models.CalendarEvent, models.EventException,
    models.CalendarEventParticipant,
)


def test_all_models_are_django_managed():
    """Django owns this schema — no ``managed=False`` shims (PLAN.md §3)."""
    for model in ALL_MODELS:
        assert model._meta.managed is True, model.__name__


def test_tables_use_idiomatic_django_names():
    """Names are Django-generated, not the alembic table names.

    Spot-checked rather than exhaustive: these four cover a plain model, a
    model whose original name had no ``task_`` prefix, a junction, and one of
    the renamed originals (``task_sequence`` -> ``tasks_tasksequence``).
    """
    assert models.Task._meta.db_table == "tasks_task"
    assert models.Label._meta.db_table == "tasks_label"
    assert models.TaskAssignee._meta.db_table == "tasks_taskassignee"
    assert models.TaskSequence._meta.db_table == "tasks_tasksequence"


@pytest.mark.django_db
def test_replica_tables_are_not_ported():
    """Р2: the user/department replicas must NOT exist.

    Their absence is the whole point of Р2 — if someone "helpfully" re-adds a
    ``task_users`` model to make a join easier, that reintroduces the
    cross-service replication this migration exists to delete, and the app
    isolation lint would not catch it (a local model is not a foreign import).
    """
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name IN "
            "('task_users', 'task_departments')"
        )
        assert cursor.fetchall() == []


def test_participant_ids_are_fk_less_integers():
    """Р2: participant columns are plain ints, not FKs into a replica."""
    for field_name in ("reporter_id", "assignee_id", "supervisor_id",
                       "department_id"):
        field = models.Task._meta.get_field(field_name)
        assert isinstance(field, dj_models.IntegerField), field_name
        assert field.related_model is None, field_name


def test_fsm_transitions_match_the_fastapi_original():
    """``TRANSITIONS`` is business logic copied 1:1 — pin it.

    Source: ``services/task/app/models/task.py``. A silent edit here changes
    which status changes the UI offers, with no other test noticing.
    """
    S = models.Status
    assert models.TRANSITIONS == {
        S.BACKLOG: frozenset({S.TODO, S.IN_PROGRESS, S.CANCELLED}),
        S.TODO: frozenset({S.IN_PROGRESS, S.BLOCKED, S.BACKLOG, S.CANCELLED}),
        S.IN_PROGRESS: frozenset({S.IN_REVIEW, S.BLOCKED, S.DONE, S.TODO,
                                  S.CANCELLED}),
        S.IN_REVIEW: frozenset({S.DONE, S.IN_PROGRESS, S.BLOCKED, S.CANCELLED}),
        S.BLOCKED: frozenset({S.IN_PROGRESS, S.TODO, S.CANCELLED}),
        S.DONE: frozenset({S.IN_PROGRESS, S.CANCELLED}),
        S.CANCELLED: frozenset({S.BACKLOG, S.TODO}),
    }
    assert models.TERMINAL_STATUSES == frozenset({S.DONE, S.CANCELLED})


@pytest.mark.django_db
def test_system_task_types_are_seeded():
    """Migration 0002 seeds the five system rows the UI and phase-10 ETL
    both assume exist."""
    rows = dict(models.TaskType.objects.filter(is_system=True)
                .values_list("slug", "name"))
    assert rows == {
        "task": "Задача", "bug": "Баг", "story": "История",
        "epic": "Эпик", "subtask": "Подзадача",
    }


@pytest.mark.django_db
def test_task_roundtrip_uses_real_column_names():
    task = models.Task.objects.create(key="TASK-1", summary="S")
    task.refresh_from_db()
    assert task.key == "TASK-1"
    assert task.status == models.Status.TODO
    assert task.priority == models.Priority.MEDIUM
    assert task.progress_percent == 0
    assert task.is_deleted is False
