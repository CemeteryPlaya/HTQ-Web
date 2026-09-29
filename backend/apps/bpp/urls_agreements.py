"""Маршруты договора ``/api/bpp/v1/agreements…`` — подмодуль ``bpp_agreements``.

``APPEND_SLASH = False``: каждый путь — в обоих написаниях. Строки явные:
сторож прав (``test_gate.py``) читает ``path(…, views.<имя>)``.
"""

from django.urls import path

from . import views_agreements as views

A = "agreements/<uuid:agreement_id>"

urlpatterns = [
    path("agreements", views.agreements_collection),
    path("agreements/", views.agreements_collection),
    path("agreements/search", views.agreement_search),
    path("agreements/search/", views.agreement_search),
    path(A, views.agreement_detail),
    path(f"{A}/", views.agreement_detail),
    path(f"{A}/submit", views.agreement_submit),
    path(f"{A}/submit/", views.agreement_submit),
    path(f"{A}/withdraw", views.agreement_withdraw),
    path(f"{A}/withdraw/", views.agreement_withdraw),
    path(f"{A}/fulfil", views.agreement_fulfil),
    path(f"{A}/fulfil/", views.agreement_fulfil),
    path(f"{A}/terminate", views.agreement_terminate),
    path(f"{A}/terminate/", views.agreement_terminate),
    path(f"{A}/supplement", views.agreement_supplement),
    path(f"{A}/supplement/", views.agreement_supplement),
    path(f"{A}/execution", views.agreement_execution),
    path(f"{A}/execution/", views.agreement_execution),
]
