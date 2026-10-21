"""``TaskDepartmentLink.kind`` (tasks/0027, канбан K1.4, спека этапа 1 S1-27).

Связь задачи с отделом бывает «участник» (``member`` — как все связи до этой
миграции) и «отправитель» (``origin`` — отдел, из которого задачу перенесли).
Ключевое — ``db_default``: старый код (откат выкатки, компания, отставшая по
миграциям) вставляет строки без ``kind``, и они обязаны стать ``member``.

``transaction=True`` — миграции это DDL; в ``finally`` схема возвращается на
последнюю миграцию аппки (приём ``test_equipment_category_migration.py``).
"""

from __future__ import annotations

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

BEFORE = ("tasks", "0026_engagement_bpp_agreement")
AFTER = ("tasks", "0027_department_link_kind")


def _migrate(target):
    executor = MigrationExecutor(connection)
    executor.loader.build_graph()
    executor.migrate([target])
    executor.loader.build_graph()
    return executor.loader.project_state([target]).apps


@pytest.fixture
def at_0026():
    try:
        yield _migrate(BEFORE)
    finally:
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(
            [key for key in executor.loader.graph.leaf_nodes() if key[0] == "tasks"]
        )


def _task(apps, key: str):
    return apps.get_model("tasks", "Task").objects.create(key=key, summary=key)


@pytest.mark.django_db(transaction=True)
def test_existing_links_become_member(at_0026):
    Link = at_0026.get_model("tasks", "TaskDepartmentLink")
    Link.objects.create(task=_task(at_0026, "MIG-1"), department_id=11)

    apps = _migrate(AFTER)
    assert list(apps.get_model("tasks", "TaskDepartmentLink")
                .objects.values_list("kind", flat=True)) == ["member"]


@pytest.mark.django_db(transaction=True)
def test_insert_without_kind_gets_member_from_db_default(at_0026):
    """Старый код не знает о ``kind`` — вставка без столбца даёт ``member``."""
    apps = _migrate(AFTER)
    task = _task(apps, "MIG-2")
    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO tasks_taskdepartmentlink (task_id, department_id) VALUES (%s, %s)",
            [task.id, 12])
        cursor.execute(
            "SELECT kind FROM tasks_taskdepartmentlink WHERE task_id = %s", [task.id])
        assert cursor.fetchone() == ("member",)
