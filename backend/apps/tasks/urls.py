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
    # Comments/attachments: the working POST lived on the tasks router
    # (trailing slash), while a second, broken router registered the
    # slash-less GET list. Both spellings are served by one dispatcher.
    path("tasks/<int:task_id>/comments", views.task_comments),
    path("tasks/<int:task_id>/comments/", views.task_comments),
    path("tasks/<int:task_id>/attachments", views.task_attachments),
    path("tasks/<int:task_id>/attachments/", views.task_attachments),
    path("tasks/<int:task_id>/activity", views.task_activity),
    path("tasks/<int:task_id>/activity/", views.task_activity),

    # Task links — frontend: 'task-links/', 'task-links/{id}/'.
    path("task-links/", views.links_collection),
    path("task-links/<int:link_id>", views.link_detail),
    path("task-links/<int:link_id>/", views.link_detail),

    # Projects — frontend: 'projects/', 'projects/{id}' and '{id}/',
    # 'projects/{id}/tasks/'.
    path("projects/", views.projects_collection),
    path("projects/<int:project_id>", views.project_detail),
    path("projects/<int:project_id>/", views.project_detail),
    path("projects/<int:project_id>/tasks", views.project_tasks),
    path("projects/<int:project_id>/tasks/", views.project_tasks),

    # Resource assignments — FastAPI declared the detail route without a
    # trailing slash, the frontend calls it with one.
    path("assignments/", views.assignments_collection),
    path("assignments/<int:assignment_id>", views.assignment_detail),
    path("assignments/<int:assignment_id>/", views.assignment_detail),

    # Calendar — frontend (api/calendar.ts) calls 'calendar/...' and
    # 'production-calendar/...'. The fixed sub-paths (timeline, users-options,
    # exceptions) are registered before '<int:event_id>' so no converter
    # change can let the id route swallow them.
    path("calendar/", views.events_collection),
    path("calendar/timeline/", views.calendar_timeline),
    path("calendar/timeline", views.calendar_timeline),
    path("calendar/users-options/", views.calendar_user_options),
    path("calendar/users-options", views.calendar_user_options),
    path("calendar/exceptions/<int:exception_id>/",
         views.event_exception_detail),
    path("calendar/<int:event_id>/", views.event_detail),
    path("calendar/<int:event_id>", views.event_detail),
    path("calendar/<int:event_id>/rsvp/", views.event_rsvp),
    path("calendar/<int:event_id>/exceptions/", views.event_exceptions),

    path("production-calendar/", views.production_calendar),
    path("production-calendar/<str:target_date>/", views.production_day_detail),
    path("production-calendar/<str:target_date>", views.production_day_detail),

    # Gantt reports — FastAPI declared both without a trailing slash; the
    # frontend calls 'reports/resource-gantt' the same way.
    path("reports/gantt", views.reports_gantt),
    path("reports/gantt/", views.reports_gantt),
    path("reports/resource-gantt", views.resource_gantt),
    path("reports/resource-gantt/", views.resource_gantt),

    # Notifications — frontend: 'notifications/', 'notifications/history/',
    # 'notifications/mark-all-read/', 'notifications/{id}/mark_read/',
    # '{id}/mark_unread/', '{id}/'. ``history/`` and ``mark-all-read/`` are
    # registered before the ``<int:notification_id>`` routes so a converter
    # change can never let the id pattern swallow them.
    path("notifications/", views.notifications_collection),
    path("notifications/history/", views.notification_history),
    path("notifications/history", views.notification_history),
    path("notifications/mark-all-read/", views.notifications_mark_all_read),
    path("notifications/mark-all-read", views.notifications_mark_all_read),
    path("notifications/<int:notification_id>/mark_read/",
         views.notification_mark_read),
    path("notifications/<int:notification_id>/mark_unread/",
         views.notification_mark_unread),
    path("notifications/<int:notification_id>", views.notification_detail),
    path("notifications/<int:notification_id>/", views.notification_detail),

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
