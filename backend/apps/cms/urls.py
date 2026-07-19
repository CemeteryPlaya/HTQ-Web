from django.urls import path

from . import views

urlpatterns = [
    path("contact-requests/", views.contact_requests_collection),
    path("contact-requests/stats", views.contact_request_stats),
    # Trailing-slash alias — ported verbatim from the FastAPI original, which
    # registers both spellings (`include_in_schema=False`) so the frontend's
    # trailing-slash call doesn't trigger a 307 that drops the Authorization
    # header on some browsers. APPEND_SLASH=False means Django won't add this
    # redirect itself, so both routes need to be explicit here too.
    path("contact-requests/stats/", views.contact_request_stats),
    path("contact-requests/<int:contact_id>/reply", views.reply_contact_request),
    path("contact-requests/<int:contact_id>", views.contact_request_detail),
]
