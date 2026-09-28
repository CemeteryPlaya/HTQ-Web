"""Маршруты «Счета организации и шаблоны выписок» ``/api/bpp/v1/bank/…``
(A3.1) — подмодуль ``bpp_bank`` (рубильник по префиксу ``/api/bpp/v1/bank``).

``APPEND_SLASH = False``: каждый путь — в обоих написаниях. Строки явные:
сторож прав (``test_gate.py``) читает ``path(…, views.<имя>)``. Ключ в
адресе — ``str``, а не ``uuid``: неверный UUID вьюха превращает в 404 с
конвертом ``{"detail": …}`` (``uuid_or_404``).
"""

from django.urls import path

from . import views_bank as views

A = "bank/accounts/<str:account_id>"
T = "bank/templates/<str:template_id>"

urlpatterns = [
    path("bank/accounts", views.accounts_collection),
    path("bank/accounts/", views.accounts_collection),
    path(A, views.account_detail),
    path(f"{A}/", views.account_detail),
    path("bank/templates", views.templates_collection),
    path("bank/templates/", views.templates_collection),
    path(T, views.template_detail),
    path(f"{T}/", views.template_detail),
    path(f"{T}/preview", views.template_preview),
    path(f"{T}/preview/", views.template_preview),
]
