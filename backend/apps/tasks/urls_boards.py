"""Маршруты канбан-досок (мастер-план §6.1–6.2). Подключаются из ``urls.py``;
``APPEND_SLASH=False`` — каждое написание регистрируется явно. Пути — явными
``path(…, views.<имя>)``: так их читает сторож прав
(``apps/access/tests/test_gate.py``)."""

from django.urls import path

from . import views_boards as views

urlpatterns = [
    path("boards", views.boards_collection),
    path("boards/", views.boards_collection),
    path("boards/personal", views.personal_board),
    path("boards/personal/", views.personal_board),
    path("boards/personal/summary", views.personal_summary),
    path("boards/personal/summary/", views.personal_summary),
    path("boards/personal/settings", views.personal_settings),
    path("boards/personal/settings/", views.personal_settings),
    path("boards/departments/<int:department_id>", views.department_board),
    path("boards/departments/<int:department_id>/", views.department_board),
    path("boards/departments/<int:department_id>/settings", views.department_settings),
    path("boards/departments/<int:department_id>/settings/", views.department_settings),
    path("boards/projects/<int:project_id>", views.project_board),
    path("boards/projects/<int:project_id>/", views.project_board),
    path("boards/projects/<int:project_id>/settings", views.project_settings),
    path("boards/projects/<int:project_id>/settings/", views.project_settings),
    path("tasks/<int:task_id>/move", views.task_move),
    path("tasks/<int:task_id>/move/", views.task_move),
    path("tasks/<int:task_id>/seen", views.task_seen),
    path("tasks/<int:task_id>/seen/", views.task_seen),
]
