"""Маршруты заявок ``/api/bpp/v1/requests…`` —
подмодуль ``bpp_requests``.

``APPEND_SLASH = False``: каждый путь — в обоих написаниях. Строки явные:
сторож прав (``test_gate.py``) читает ``path(…, views.<имя>)``.
"""

from django.urls import path

from . import views_requests as views

R = "requests/<uuid:request_id>"

urlpatterns = [
    path("requests", views.requests_collection),
    path("requests/", views.requests_collection),
    path(R, views.request_detail),
    path(f"{R}/", views.request_detail),
    path(f"{R}/submit", views.request_submit),
    path(f"{R}/submit/", views.request_submit),
    path(f"{R}/withdraw", views.request_withdraw),
    path(f"{R}/withdraw/", views.request_withdraw),
    path(f"{R}/cancel", views.request_cancel),
    path(f"{R}/cancel/", views.request_cancel),
    path(f"{R}/close-remainder", views.request_close_remainder),
    path(f"{R}/close-remainder/", views.request_close_remainder),
    path(f"{R}/copy", views.request_copy),
    path(f"{R}/copy/", views.request_copy),
    path(f"{R}/execution", views.request_execution),
    path(f"{R}/execution/", views.request_execution),
    path(f"{R}/print", views.request_print),
    path(f"{R}/print/", views.request_print),
    # Документы заявки — панель /api/files/v1/bpp.purchase_request/<id>/files/
    # (владелец в apps/bpp/file_owners.py); своих ручек файлов у заявки нет.
]
