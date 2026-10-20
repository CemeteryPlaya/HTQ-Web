"""Маршруты тендера ``/api/tender/v1/tenders…`` (T2.1, T2.2).

``APPEND_SLASH = False``: каждый путь — в обоих написаниях. Строки явные:
сторож прав (``apps/access/tests/test_gate.py``) читает ``path(…, views.<имя>)``.
Ключи — строкой: неверный UUID — 404 сервиса, а не «маршрут не найден».
"""

from django.urls import path

from . import views_tenders as views

T = "tenders/<str:tender_id>"
INV = f"{T}/invitations/<str:invitation_id>"

urlpatterns = [
    path("tenders", views.tenders_collection),
    path("tenders/", views.tenders_collection),
    path(T, views.tender_detail),
    path(f"{T}/", views.tender_detail),
    path(f"{T}/payment-scheme", views.tender_payment_scheme),
    path(f"{T}/payment-scheme/", views.tender_payment_scheme),
    path(f"{T}/publish", views.tender_publish),
    path(f"{T}/publish/", views.tender_publish),
    path(f"{T}/extend", views.tender_extend),
    path(f"{T}/extend/", views.tender_extend),
    path(f"{T}/cancel", views.tender_cancel),
    path(f"{T}/cancel/", views.tender_cancel),
    # Этап 5: вскрытие, сравнение, выбор, передача, поставка.
    path(f"{T}/open", views.tender_open),
    path(f"{T}/open/", views.tender_open),
    path(f"{T}/comparison", views.tender_comparison),
    path(f"{T}/comparison/", views.tender_comparison),
    path(f"{T}/comparison/export", views.tender_comparison_export),
    path(f"{T}/award", views.tender_award),
    path(f"{T}/award/", views.tender_award),
    path(f"{T}/award/submit", views.tender_award_submit),
    path(f"{T}/handover", views.tender_handover),
    path(f"{T}/handover/", views.tender_handover),
    path(f"{T}/delivery", views.tender_delivery),
    path(f"{T}/delivery/", views.tender_delivery),
    path(f"{T}/receipts", views.tender_receipts),
    path(f"{T}/receipts/", views.tender_receipts),
    path(f"{T}/receipts/<str:receipt_id>", views.tender_receipt_originals),
    path(f"{T}/receipts/<str:receipt_id>/", views.tender_receipt_originals),
    path(f"{T}/receipts/<str:receipt_id>/cancel", views.tender_receipt_cancel),
    path(f"{T}/receipts/<str:receipt_id>/cancel/", views.tender_receipt_cancel),
    path(f"{T}/award/submit/", views.tender_award_submit),
    path(f"{T}/comparison/export/", views.tender_comparison_export),
    path(f"{T}/offers/<str:offer_id>/files/<str:doc_id>", views.tender_offer_file),
    path(f"{T}/offers/<str:offer_id>/files/<str:doc_id>/", views.tender_offer_file),
    path(f"{T}/invitations", views.invitations_collection),
    path(f"{T}/invitations/", views.invitations_collection),
    path(f"{INV}/revoke", views.invitation_revoke),
    path(f"{INV}/revoke/", views.invitation_revoke),
    path(f"{INV}/reissue", views.invitation_reissue),
    path(f"{INV}/reissue/", views.invitation_reissue),
    path(f"{INV}/reset-device", views.invitation_reset_device),
    path(f"{INV}/reset-device/", views.invitation_reset_device),
    path(f"{INV}/events", views.invitation_events),
    path(f"{INV}/events/", views.invitation_events),
]
