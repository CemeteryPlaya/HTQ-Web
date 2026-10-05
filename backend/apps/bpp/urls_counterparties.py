"""Маршруты справочника «Контрагенты» ``/api/bpp/v1/counterparties…`` (A2.3).

``APPEND_SLASH = False``: каждый путь — в обоих написаниях. Строки явные:
сторож прав (``test_gate.py``) читает ``path(…, views.<имя>)``. Ключ в
адресе — ``str``, а не ``uuid``: неверный UUID вьюха превращает в 404 с
конвертом ``{"detail": …}`` (``uuid_or_404``), а не в HTML-страницу Django.
Счета (``counterparties/accounts/…``) стоят первыми — до шаблона с ключом
контрагента.
"""

from django.urls import path

from . import views_counterparties as views

C = "counterparties/<str:counterparty_id>"
A = "counterparties/accounts/<str:account_id>"

urlpatterns = [
    path("counterparties", views.counterparties_collection),
    path("counterparties/", views.counterparties_collection),
    path(A, views.account_patch),
    path(f"{A}/", views.account_patch),
    path(C, views.counterparty_detail),
    path(f"{C}/", views.counterparty_detail),
    path(f"{C}/block", views.counterparty_block),
    path(f"{C}/block/", views.counterparty_block),
    path(f"{C}/unblock", views.counterparty_unblock),
    path(f"{C}/unblock/", views.counterparty_unblock),
    path(f"{C}/archive", views.counterparty_archive),
    path(f"{C}/archive/", views.counterparty_archive),
    path(f"{C}/verified", views.counterparty_verified),
    path(f"{C}/verified/", views.counterparty_verified),
    path(f"{C}/accounts", views.counterparty_accounts),
    path(f"{C}/accounts/", views.counterparty_accounts),
]
