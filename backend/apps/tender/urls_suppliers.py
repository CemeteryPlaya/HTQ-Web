"""Маршруты справочников участников ``/api/tender/v1/{contacts,prospects,
counterparties}…`` (T2.2).

``APPEND_SLASH = False``: каждый путь — в обоих написаниях. Строки явные:
сторож прав (``apps/access/tests/test_gate.py``) читает ``path(…, views.<имя>)``.
"""

from django.urls import path

from . import views_suppliers as views

urlpatterns = [
    path("contacts", views.contacts_collection),
    path("contacts/", views.contacts_collection),
    path("contacts/<str:contact_id>", views.contact_detail),
    path("contacts/<str:contact_id>/", views.contact_detail),
    path("prospects", views.prospects_collection),
    path("prospects/", views.prospects_collection),
    path("prospects/<str:prospect_id>", views.prospect_detail),
    path("prospects/<str:prospect_id>/", views.prospect_detail),
    path("counterparties", views.counterparty_search),
    path("counterparties/", views.counterparty_search),
]
