"""Route table for ``/api/tasks/v1/`` (mounted by URL autodiscovery — see
``TasksConfig.API_PREFIX`` and ``htqweb/urls.py``).

``APPEND_SLASH=False``, so Django never redirects a stray trailing slash on
its own: **every spelling a client actually uses must be registered here**
(PLAN.md §3 — "слеши дважды ловили 404"). The spellings below were taken
from two sources, not guessed:

* the FastAPI route declarations in ``services/task/app/api/v1/*.py``;
* an audit of the real call sites in ``frontend/src/api/tasks.ts`` and
  ``frontend/src/api/calendar.ts``.

Where the two disagree — the frontend calls ``equipment/{id}/`` while
FastAPI declared ``equipment/{id}`` (FastAPI's ``redirect_slashes`` papered
over it with a 307) — BOTH are registered, because a 307 that drops the
``Authorization`` header on some browsers is exactly the failure this
convention exists to prevent.
"""

from django.urls import path

from . import views

urlpatterns = [
    # Tasks. ``stats/`` is registered BEFORE the ``<int:task_id>`` detail
    # route so it can never be shadowed — Django matches in order, and while
    # "stats" would not parse as an int today, an accidental <str:> converter
    # later would silently swallow it.
    path("tasks/", views.tasks_collection),
    path("tasks/stats/", views.task_stats),
    path("tasks/stats", views.task_stats),
    path("tasks/<int:task_id>", views.task_detail),
    path("tasks/<int:task_id>/", views.task_detail),
    path("tasks/<int:task_id>/transitions/", views.task_transitions),
    path("tasks/<int:task_id>/assignees/", views.update_assignees),
    path("tasks/<int:task_id>/supervisor/", views.update_supervisor),
    path("tasks/<int:task_id>/delegates/", views.task_delegates),
    path("tasks/<int:task_id>/delegates/<int:user_id>/", views.remove_delegate),
    path("tasks/<int:task_id>/watch/", views.task_watch),
    path("tasks/<int:task_id>/progress/", views.update_progress),

    # Labels — frontend: 'labels/', 'labels/{id}/'.
    path("labels/", views.labels_collection),
    path("labels/<int:label_id>", views.label_detail),
    path("labels/<int:label_id>/", views.label_detail),

    # Task types — frontend: 'task-types/', 'task-types/{id}/'.
    path("task-types/", views.task_types_collection),
    path("task-types/<int:type_id>", views.task_type_detail),
    path("task-types/<int:type_id>/", views.task_type_detail),

    # Equipment — FastAPI declared the detail route WITHOUT a trailing
    # slash, the frontend calls it WITH one; both registered (see docstring).
    path("equipment/", views.equipment_collection),
    path("equipment/<int:equipment_id>", views.equipment_detail),
    path("equipment/<int:equipment_id>/", views.equipment_detail),

    # Sequences — admin-only key vending. No frontend call site; kept
    # because the route is part of the published contract.
    path("sequences/<str:project_prefix>/next", views.next_task_key),
    path("sequences/<str:project_prefix>/next/", views.next_task_key),
]
