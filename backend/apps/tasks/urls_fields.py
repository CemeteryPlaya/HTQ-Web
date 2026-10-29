"""Маршруты своих полей досок (решение K-35, канбан, этап S3). Подключаются из
``urls.py``; ``APPEND_SLASH=False`` — каждое написание регистрируется явно,
пути — явными ``path(…, views.<имя>)`` для сторожа прав (``test_gate.py``)."""

from django.urls import path

from . import views_fields as views

urlpatterns = [
    path("boards/departments/<int:department_id>/fields", views.department_fields),
    path("boards/departments/<int:department_id>/fields/", views.department_fields),
    path("boards/projects/<int:project_id>/fields", views.project_fields),
    path("boards/projects/<int:project_id>/fields/", views.project_fields),
    path("boards/fields/<int:field_id>", views.field_detail),
    path("boards/fields/<int:field_id>/", views.field_detail),
    path("tasks/<int:task_id>/fields/<int:field_id>", views.task_field_value),
    path("tasks/<int:task_id>/fields/<int:field_id>/", views.task_field_value),
]
