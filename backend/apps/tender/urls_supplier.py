"""Маршруты портала поставщика ``/api/tender/v1/supplier/<token>/…`` (T3.2).

``APPEND_SLASH = False``: каждый путь — в обоих написаниях. Строки явные:
сторож прав (``apps/access/tests/test_gate.py``) читает ``path(…, views.<имя>)``.
Токен — строкой: невозможный токен отвечает тем же 404, что и неизвестный.
Ручки предложения и файлов КП (T3.3/T3.4) дописываются сюда же.
"""

from django.urls import path

from . import views_supplier as views

S = "supplier/<str:token>"

urlpatterns = [
    path(S, views.portal_card),
    path(f"{S}/", views.portal_card),
    path(f"{S}/bind", views.portal_bind),
    path(f"{S}/bind/", views.portal_bind),
    path(f"{S}/tender", views.portal_tender),
    path(f"{S}/tender/", views.portal_tender),
    path(f"{S}/files/<str:doc_id>", views.portal_spec_file),
    path(f"{S}/files/<str:doc_id>/", views.portal_spec_file),
    # Предложение и файлы КП (T3.3/T3.4).
    path(f"{S}/offer", views.portal_offer),
    path(f"{S}/offer/", views.portal_offer),
    path(f"{S}/offer/submit", views.portal_offer_submit),
    path(f"{S}/offer/submit/", views.portal_offer_submit),
    path(f"{S}/offer/withdraw", views.portal_offer_withdraw),
    path(f"{S}/offer/withdraw/", views.portal_offer_withdraw),
    path(f"{S}/offer/files", views.portal_offer_files),
    path(f"{S}/offer/files/", views.portal_offer_files),
    path(f"{S}/offer/files/<str:doc_id>", views.portal_offer_file_delete),
    path(f"{S}/offer/files/<str:doc_id>/", views.portal_offer_file_delete),
    path(f"{S}/decline", views.portal_decline),
    path(f"{S}/decline/", views.portal_decline),
]
