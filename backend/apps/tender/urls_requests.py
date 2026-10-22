"""Маршруты заявки ``/api/tender/v1/requests…`` (T1.1, T1.3).

``APPEND_SLASH = False``: каждый путь — в обоих написаниях. Строки явные:
сторож прав (``apps/access/tests/test_gate.py``) читает ``path(…, views.<имя>)``.
Ключ — строкой: неверный UUID — 404 сервиса, а не «маршрут не найден».
"""

from django.urls import path

from . import views_requests as views

R = "requests/<str:request_id>"

urlpatterns = [
    path("requests", views.requests_collection),
    path("requests/", views.requests_collection),
    # Подсказки формы (T1.3) — ДО ``requests/<id>``, иначе слово станет ключом.
    path("requests/budget", views.request_budget),
    path("requests/budget/", views.request_budget),
    path("requests/articles", views.request_articles),
    path("requests/articles/", views.request_articles),
    path("requests/projects", views.request_projects),
    path("requests/projects/", views.request_projects),
    path(R, views.request_detail),
    path(f"{R}/", views.request_detail),
    path(f"{R}/submit", views.request_submit),
    path(f"{R}/submit/", views.request_submit),
    path(f"{R}/withdraw", views.request_withdraw),
    path(f"{R}/withdraw/", views.request_withdraw),
    path(f"{R}/cancel", views.request_cancel),
    path(f"{R}/cancel/", views.request_cancel),
    path(f"{R}/parts/<str:part_id>/exclude", views.request_part_exclude),
    path(f"{R}/parts/<str:part_id>/exclude/", views.request_part_exclude),
    # Документы заявки (ТЗ, чертежи) — панель /api/files/v1/tender.request/<id>/files/
    # (владелец в apps/tender/file_owners.py); своих ручек файлов у заявки нет.
]
