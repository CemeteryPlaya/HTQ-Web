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
    # Объёмы работ задачи — ПЛАН («развезти 250 валов»). Факт приходит
    # ежедневными отчётами ниже.
    path("tasks/<int:task_id>/volumes", views.task_volumes),
    path("tasks/<int:task_id>/volumes/", views.task_volumes),
    # Ежедневные отчёты: сколько сделали и КОГДА (дата выполнения работ,
    # не заполнения). Единственный источник факта выполнения.
    path("tasks/<int:task_id>/daily-reports", views.task_daily_reports),
    path("tasks/<int:task_id>/daily-reports/", views.task_daily_reports),

    # Сводка «что отчитать за день». Фиксированный путь ДО <int:>,
    # иначе "board" ушло бы в конвертер и дало 404.
    path("daily-reports/board", views.daily_report_board),
    path("daily-reports/board/", views.daily_report_board),

    path("daily-reports/<int:report_id>", views.daily_report_detail),
    path("daily-reports/<int:report_id>/", views.daily_report_detail),
    path("daily-reports/<int:report_id>/revisions",
         views.daily_report_revisions),
    path("daily-reports/<int:report_id>/revisions/",
         views.daily_report_revisions),

    # Task links — frontend: 'task-links/', 'task-links/{id}/'.
    path("task-links/", views.links_collection),
    path("task-links/<int:link_id>", views.link_detail),
    path("task-links/<int:link_id>/", views.link_detail),

    # Contractors (субподрядчики) — new domain, no FastAPI original.
    path("contractors/", views.contractors_collection),
    path("contractors", views.contractors_collection),
    path("contractors/<int:contractor_id>", views.contractor_detail),
    path("contractors/<int:contractor_id>/", views.contractor_detail),
    path("contractors/<int:contractor_id>/workers", views.contractor_workers),
    path("contractors/<int:contractor_id>/workers/", views.contractor_workers),
    path("contractor-workers/<int:worker_id>", views.contractor_worker_detail),
    path("contractor-workers/<int:worker_id>/", views.contractor_worker_detail),
    path("contractor-engagements/", views.engagements_collection),
    path("contractor-engagements", views.engagements_collection),
    path("contractor-engagements/<int:engagement_id>", views.engagement_detail),
    path("contractor-engagements/<int:engagement_id>/", views.engagement_detail),

    # Sites (объекты/площадки) — new domain, no FastAPI original. Both
    # spellings registered from the start, same convention as everything
    # else here.
    path("sites/", views.sites_collection),
    path("sites", views.sites_collection),
    path("sites/<int:site_id>", views.site_detail),
    path("sites/<int:site_id>/", views.site_detail),
    path("sites/<int:site_id>/tasks", views.site_tasks),
    path("sites/<int:site_id>/tasks/", views.site_tasks),

    # Блоки объекта (Сазаган → блок 1, блок 2, …). Коллекция висит на
    # объекте, деталь — на своём id: блок правят из карточки блока, а не
    # прокликивая площадку заново.
    path("sites/<int:site_id>/blocks", views.site_blocks_collection),
    path("sites/<int:site_id>/blocks/", views.site_blocks_collection),
    path("blocks/<int:block_id>", views.block_detail),
    path("blocks/<int:block_id>/", views.block_detail),
    path("blocks/<int:block_id>/volumes", views.block_volumes),
    path("blocks/<int:block_id>/volumes/", views.block_volumes),
    path("blocks/<int:block_id>/progress", views.block_progress),
    path("blocks/<int:block_id>/progress/", views.block_progress),

    # Роудмапы (пакеты работ на объекте) — уровень между объектом и задачей.
    path("roadmaps/", views.roadmaps_collection),
    path("roadmaps", views.roadmaps_collection),
    path("roadmaps/<int:roadmap_id>", views.roadmap_detail),
    path("roadmaps/<int:roadmap_id>/", views.roadmap_detail),
    path("roadmaps/<int:roadmap_id>/tasks", views.roadmap_tasks),
    path("roadmaps/<int:roadmap_id>/tasks/", views.roadmap_tasks),
    path("roadmaps/<int:roadmap_id>/metrics", views.roadmap_metrics),
    path("roadmaps/<int:roadmap_id>/metrics/", views.roadmap_metrics),
    path("roadmaps/<int:roadmap_id>/daily-reports",
         views.roadmap_daily_reports),
    path("roadmaps/<int:roadmap_id>/daily-reports/",
         views.roadmap_daily_reports),

    # Projects — frontend: 'projects/', 'projects/{id}' and '{id}/',
    # 'projects/{id}/tasks/'.
    path("projects/", views.projects_collection),
    path("projects/<int:project_id>", views.project_detail),
    path("projects/<int:project_id>/", views.project_detail),
    path("projects/<int:project_id>/tasks", views.project_tasks),
    path("projects/<int:project_id>/tasks/", views.project_tasks),
    path("projects/<int:project_id>/sites", views.project_sites),
    path("projects/<int:project_id>/sites/", views.project_sites),

    # Resource assignments — FastAPI declared the detail route without a
    # trailing slash, the frontend calls it with one. Путь сохранён при
    # переименовании модели в ResourceAllocation: ломать опубликованный
    # маршрут ради внутреннего названия незачем.
    path("assignments/", views.assignments_collection),
    path("assignments/<int:assignment_id>", views.assignment_detail),
    path("assignments/<int:assignment_id>/", views.assignment_detail),

    # Потребность в ресурсах количеством («2 человека», «2 кары») — план
    # рядом с фактом-назначениями выше.
    path("resource-requirements/", views.requirements_collection),
    path("resource-requirements", views.requirements_collection),
    path("resource-requirements/<int:requirement_id>",
         views.requirement_detail),
    path("resource-requirements/<int:requirement_id>/",
         views.requirement_detail),

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
    # План/факт с прогнозом. Отчётная дата — ?date=, по умолчанию сегодня.
    path("plan-fact/project/<int:project_id>", views.project_plan_fact),
    path("plan-fact/project/<int:project_id>/", views.project_plan_fact),
    path("plan-fact/roadmap/<int:roadmap_id>", views.roadmap_plan_fact),
    path("plan-fact/roadmap/<int:roadmap_id>/", views.roadmap_plan_fact),

    # Учёт задействования техники: что занято на дату D + история
    # интервалов. Отдельная ручка, а не поле в отчётах: узел иерархии
    # задаётся параметром, и это самостоятельный вопрос.
    path("equipment-usage", views.equipment_usage),
    path("equipment-usage/", views.equipment_usage),

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

    # Плоские справочники планирования: типы техники («кара»), роли людей
    # («монтажник»), виды объёмов («валы»). Форма ручек одинаковая — вьюхи
    # собраны одной фабрикой, см. views._reference_endpoints.
    path("equipment-categories/", views.equipment_categories_collection),
    path("equipment-categories/<int:row_id>", views.equipment_category_detail),
    path("equipment-categories/<int:row_id>/", views.equipment_category_detail),
    path("work-roles/", views.work_roles_collection),
    path("work-roles/<int:row_id>", views.work_role_detail),
    path("work-roles/<int:row_id>/", views.work_role_detail),
    path("volume-types/", views.volume_types_collection),
    path("volume-types/<int:row_id>", views.volume_type_detail),
    path("volume-types/<int:row_id>/", views.volume_type_detail),

    # Sequences — admin-only key vending. No frontend call site; kept
    # because the route is part of the published contract.
    path("sequences/<str:project_prefix>/next", views.next_task_key),
    path("sequences/<str:project_prefix>/next/", views.next_task_key),
]
