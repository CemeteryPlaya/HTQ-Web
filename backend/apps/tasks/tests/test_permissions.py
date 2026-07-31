"""Authorisation tests for the tasks domain.

These cover the gap the visibility model had until now: ``scope_for`` /
``visibility_q`` narrowed the task LIST correctly, but a task's
sub-resources — its transitions, comments, attachments, activity log and
booked resources — were reachable by id from any authenticated account. So
was every write on the shared dictionaries (labels, equipment) and on
projects. Filtering the list while leaving the parts open is not a
permission model; it is a suggestion.

Two conventions asserted throughout:

* **404, not 403, for anything out of scope.** A 403 confirms the row
  exists. ``load_for_action`` -> ``get_task`` -> ``Http404`` keeps a task
  the caller may not see indistinguishable from one that was never there.
* **403 for a visible row the caller may not change.** Here the existence
  is not a secret — the refusal is about rights, and the caller deserves to
  be told which of the two problems they have.

Task types are deliberately absent from the admin-gate cases: the business
wants inline type creation available to everyone who can file a task (see
the section comment in ``views.py``).
"""

from __future__ import annotations

import pytest
from django.test import Client

from apps.tasks.models import (
    Equipment, Label, Project, Task, ResourceAllocation, TaskComment,
    TaskVolume, TaskWatcher, WorkVolumeType,
)

from .helpers import (BASE, admin_token, auth, patch_json, post_json,
                      put_json)

USER = 7            # helpers.token()
ADMIN = 9           # helpers.admin_token()
STRANGER = 4242     # nobody's id


def _mine(**over) -> Task:
    """A task the regular caller participates in (as reporter)."""
    fields = {"key": f"TASK-{Task.objects.count() + 1}", "summary": "S",
              "reporter_id": USER}
    fields.update(over)
    return Task.objects.create(**fields)


def _theirs(**over) -> Task:
    """A task the regular caller has no part in and no department claim on."""
    fields = {"key": f"TASK-{Task.objects.count() + 1}", "summary": "S",
              "reporter_id": STRANGER, "assignee_id": STRANGER}
    fields.update(over)
    return Task.objects.create(**fields)


# ─────────────────────────────────────────────────────────────────────────
# A task's sub-resources follow the task's visibility
# ─────────────────────────────────────────────────────────────────────────

SUBRESOURCES = [
    "transitions/",
    "comments",
    "comments/",
    "attachments",
    "attachments/",
    "activity",
    "activity/",
]


@pytest.mark.django_db
@pytest.mark.parametrize("suffix", SUBRESOURCES)
def test_subresources_of_an_invisible_task_are_404(suffix):
    task = _theirs()
    TaskComment.objects.create(task=task, author_id=STRANGER, body="секрет")
    resp = Client().get(f"{BASE}/tasks/{task.id}/{suffix}", **auth())
    assert resp.status_code == 404, suffix


@pytest.mark.django_db
@pytest.mark.parametrize("suffix", SUBRESOURCES)
def test_subresources_of_my_own_task_are_200(suffix):
    task = _mine()
    resp = Client().get(f"{BASE}/tasks/{task.id}/{suffix}", **auth())
    assert resp.status_code == 200, suffix


@pytest.mark.django_db
def test_invisible_task_and_missing_task_answer_alike():
    """The status code must not tell an outsider which ids are real."""
    theirs = _theirs()
    client = Client()
    existing = client.get(f"{BASE}/tasks/{theirs.id}/comments", **auth())
    missing = client.get(f"{BASE}/tasks/99999/comments", **auth())
    assert existing.status_code == missing.status_code == 404


@pytest.mark.django_db
def test_cannot_comment_on_an_invisible_task():
    task = _theirs()
    resp = post_json(Client(), f"{BASE}/tasks/{task.id}/comments/",
                     {"body": "подсматриваю"}, **auth())
    assert resp.status_code == 404
    assert not TaskComment.objects.filter(task=task).exists()


@pytest.mark.django_db
def test_can_comment_on_a_task_i_can_see():
    """Commenting needs visibility, NOT edit rights — participation is not
    editing."""
    task = _mine()
    resp = post_json(Client(), f"{BASE}/tasks/{task.id}/comments/",
                     {"body": "по делу"}, **auth())
    assert resp.status_code == 201


# ─────────────────────────────────────────────────────────────────────────
# Resource assignments — planning, so full edit is required
# ─────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_listing_resources_of_an_invisible_task_is_404():
    task = _theirs()
    ResourceAllocation.objects.create(task=task, employee_id=STRANGER)
    resp = Client().get(f"{BASE}/assignments/?task_id={task.id}", **auth())
    assert resp.status_code == 404


@pytest.mark.django_db
def test_booking_a_resource_on_an_invisible_task_is_404():
    task = _theirs()
    equipment = Equipment.objects.create(name="Кран")
    resp = post_json(Client(), f"{BASE}/assignments/",
                     {"task_id": task.id, "equipment_id": equipment.id},
                     **auth())
    assert resp.status_code == 404
    assert not ResourceAllocation.objects.filter(task=task).exists()


@pytest.mark.django_db
def test_booking_a_resource_needs_full_edit_not_just_visibility():
    """A plain assignee can report progress but must not re-plan the crew's
    machinery — that is what require_full_edit buys here."""
    task = _mine(reporter_id=STRANGER, assignee_id=USER)
    equipment = Equipment.objects.create(name="Погрузчик")
    resp = post_json(Client(), f"{BASE}/assignments/",
                     {"task_id": task.id, "equipment_id": equipment.id},
                     **auth())
    assert resp.status_code == 403


# ─────────────────────────────────────────────────────────────────────────
# Плановый объём задачи — «мягкое» право, не полное
#
# Фронт зеркалит это правило (``lib/tasks/dailyReport.canReportOnTask``),
# чтобы не рисовать кнопку, дающую 403. Зеркало без теста на оригинал
# сторожит только само себя, поэтому правило закреплено с обеих сторон.
# ─────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_setting_the_planned_volume_is_a_soft_edit_right():
    """Исполнитель задаёт плановый объём своей задачи сам.

    Требовать здесь полного права значило бы сделать отчётность
    невозможной: вид работ у отчёта берётся из объёмов, и без права их
    завести исполнитель не может отчитаться вообще.
    """
    task = _mine(reporter_id=STRANGER, assignee_id=USER)
    volume_type = WorkVolumeType.objects.create(slug="valy", name="Валы")
    resp = put_json(Client(), f"{BASE}/tasks/{task.id}/volumes",
                    {"volumes": [{"volume_type_id": volume_type.id,
                                  "planned_quantity": 250}]},
                    **auth())
    assert resp.status_code == 200
    assert TaskVolume.objects.filter(task=task).count() == 1


@pytest.mark.django_db
def test_a_stranger_cannot_set_the_planned_volume():
    """404, а не 403: задача вне видимости не должна подтверждать, что она
    есть — та же конвенция, что у остальных подресурсов."""
    task = _theirs()
    volume_type = WorkVolumeType.objects.create(slug="valy", name="Валы")
    resp = put_json(Client(), f"{BASE}/tasks/{task.id}/volumes",
                    {"volumes": [{"volume_type_id": volume_type.id,
                                  "planned_quantity": 250}]},
                    **auth())
    assert resp.status_code == 404
    assert not TaskVolume.objects.filter(task=task).exists()


@pytest.mark.django_db
def test_a_watcher_cannot_set_the_planned_volume():
    """Видимость и право отчитаться — разные вещи.

    Наблюдатель числится участником для ВИДИМОСТИ (``_participant_q``), но
    не для ``can_progress``: следить за задачей и заявлять о выполненном
    объёме — не одно и то же. Здесь 403, а не 404, потому что существование
    задачи для наблюдателя не секрет — отказ именно про права.
    """
    task = _theirs()
    TaskWatcher.objects.create(task=task, user_id=USER)
    volume_type = WorkVolumeType.objects.create(slug="valy", name="Валы")
    resp = put_json(Client(), f"{BASE}/tasks/{task.id}/volumes",
                    {"volumes": [{"volume_type_id": volume_type.id,
                                  "planned_quantity": 250}]},
                    **auth())
    assert resp.status_code == 403
    assert not TaskVolume.objects.filter(task=task).exists()


@pytest.mark.django_db
def test_unbooking_a_resource_of_an_invisible_task_is_404():
    task = _theirs()
    row = ResourceAllocation.objects.create(task=task, employee_id=STRANGER)
    resp = Client().delete(f"{BASE}/assignments/{row.id}/", **auth())
    assert resp.status_code == 404
    assert ResourceAllocation.objects.filter(pk=row.id).exists()


# ─────────────────────────────────────────────────────────────────────────
# Links — both endpoints are checked, because a link is a two-way fact
# ─────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_cannot_link_to_a_task_i_cannot_see():
    """Otherwise the response (and the other card) would leak the hidden
    task's key and summary."""
    mine, theirs = _mine(), _theirs()
    resp = post_json(Client(), f"{BASE}/task-links/",
                     {"source_id": mine.id, "target_id": theirs.id,
                      "link_type": "blocks"}, **auth())
    assert resp.status_code == 404


@pytest.mark.django_db
def test_cannot_link_from_a_task_i_cannot_edit():
    mine = _mine()
    watched = _mine(reporter_id=STRANGER, assignee_id=USER)
    resp = post_json(Client(), f"{BASE}/task-links/",
                     {"source_id": watched.id, "target_id": mine.id,
                      "link_type": "blocks"}, **auth())
    assert resp.status_code == 403


# ─────────────────────────────────────────────────────────────────────────
# Shared dictionaries: reads open, writes admin-only
# ─────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
@pytest.mark.parametrize("path", ["labels/", "equipment/", "task-types/"])
def test_dictionary_reads_stay_open(path):
    resp = Client().get(f"{BASE}/{path}", **auth())
    assert resp.status_code == 200


@pytest.mark.django_db
def test_regular_user_cannot_create_a_label():
    resp = post_json(Client(), f"{BASE}/labels/", {"name": "самодел"},
                     **auth())
    assert resp.status_code == 403
    assert not Label.objects.filter(name="самодел").exists()


@pytest.mark.django_db
def test_regular_user_cannot_rename_or_delete_a_label():
    label = Label.objects.create(name="ops")
    client = Client()
    assert patch_json(client, f"{BASE}/labels/{label.id}/", {"name": "x"},
                      **auth()).status_code == 403
    assert client.delete(f"{BASE}/labels/{label.id}/",
                         **auth()).status_code == 403
    label.refresh_from_db()
    assert label.name == "ops"


@pytest.mark.django_db
def test_regular_user_cannot_touch_the_equipment_register():
    equipment = Equipment.objects.create(name="Экскаватор")
    client = Client()
    assert post_json(client, f"{BASE}/equipment/", {"name": "Свой кран"},
                     **auth()).status_code == 403
    assert patch_json(client, f"{BASE}/equipment/{equipment.id}/",
                      {"name": "Переименован"}, **auth()).status_code == 403
    assert client.delete(f"{BASE}/equipment/{equipment.id}/",
                         **auth()).status_code == 403
    equipment.refresh_from_db()
    assert equipment.name == "Экскаватор"
    assert equipment.is_active is True


@pytest.mark.django_db
def test_task_types_are_not_admin_gated():
    """Explicit business decision: the task form creates types inline, and
    that must keep working for everyone who can file a task."""
    resp = post_json(Client(), f"{BASE}/task-types/",
                     {"name": "Обслуживание"}, **auth())
    assert resp.status_code == 201


# ─────────────────────────────────────────────────────────────────────────
# Projects
# ─────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_regular_user_cannot_create_a_project():
    resp = post_json(Client(), f"{BASE}/projects/", {"name": "Мой проект"},
                     **auth())
    assert resp.status_code == 403
    assert not Project.objects.filter(name="Мой проект").exists()


@pytest.mark.django_db
def test_regular_user_cannot_edit_or_delete_a_project_out_of_scope():
    """hr is unreachable in tests, so the caller resolves to no department
    and every project is out of scope -> 404, never 403."""
    project = Project.objects.create(name="Чужой", owner_id=STRANGER)
    client = Client()
    assert patch_json(client, f"{BASE}/projects/{project.id}/",
                      {"name": "Захвачен"}, **auth()).status_code == 404
    assert client.delete(f"{BASE}/projects/{project.id}/",
                         **auth()).status_code == 404
    project.refresh_from_db()
    assert project.name == "Чужой"


@pytest.mark.django_db
def test_admin_who_is_not_the_owner_can_still_edit():
    project = Project.objects.create(name="Общий", owner_id=STRANGER)
    resp = patch_json(Client(), f"{BASE}/projects/{project.id}/",
                      {"name": "Отредактирован"}, **auth(admin_token()))
    assert resp.status_code == 200


@pytest.mark.django_db
def test_project_tasks_are_narrowed_to_what_the_caller_may_see():
    """Seeing the project is not seeing every task in it. Before this the
    endpoint narrowed by department only, and handed over the rest."""
    project = Project.objects.create(name="Смешанный", owner_id=ADMIN)
    mine = _mine(project=project)
    _theirs(project=project)

    admin_view = Client().get(f"{BASE}/projects/{project.id}/tasks/",
                              **auth(admin_token()))
    assert admin_view.status_code == 200
    assert len(admin_view.json()) == 2

    # The regular caller cannot see the project at all here (no department),
    # so the 404 fires before any task is listed — the stronger guarantee.
    mine_view = Client().get(f"{BASE}/projects/{project.id}/tasks/", **auth())
    assert mine_view.status_code == 404
    assert mine.project_id == project.id
