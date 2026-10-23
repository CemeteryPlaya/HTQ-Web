"""Маршруты запросов доступа (мастер-план канбана §6.2). Подключаются из
``urls.py``; ``APPEND_SLASH=False`` — каждое написание регистрируется явно,
пути — явными ``path(…, views.<имя>)`` для сторожа прав (``test_gate.py``)."""

from django.urls import path

from . import views_access as views

urlpatterns = [
    path("tasks/<int:task_id>/access-requests", views.task_access_requests),
    path("tasks/<int:task_id>/access-requests/", views.task_access_requests),
    path("access-requests/inbox", views.access_requests_inbox),
    path("access-requests/inbox/", views.access_requests_inbox),
    path("access-requests/<int:request_id>", views.access_request_cancel),
    path("access-requests/<int:request_id>/", views.access_request_cancel),
    path("access-requests/<int:request_id>/approve", views.access_request_approve),
    path("access-requests/<int:request_id>/approve/", views.access_request_approve),
    path("access-requests/<int:request_id>/reject", views.access_request_reject),
    path("access-requests/<int:request_id>/reject/", views.access_request_reject),
    path("boards/departments/<int:department_id>/access-history",
         views.department_access_history),
    path("boards/departments/<int:department_id>/access-history/",
         views.department_access_history),
]
