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
    # Same story for the detail/reply routes: the real frontend
    # (AdminContacts.tsx) calls `contact-requests/{id}/` (PATCH, DELETE) WITH
    # a trailing slash. Both spellings are registered so that spelling 404s.
    path("contact-requests/<int:contact_id>/reply", views.reply_contact_request),
    path("contact-requests/<int:contact_id>/reply/", views.reply_contact_request),
    path("contact-requests/<int:contact_id>", views.contact_request_detail),
    path("contact-requests/<int:contact_id>/", views.contact_request_detail),
    # conference/config — both the frontend call-site spellings (neither
    # actually sends a trailing slash: api/cms.ts's apiPath('cms',
    # 'conference/config') and ConferencePage.tsx's literal
    # 'cms/v1/conference/config'), plus the trailing-slash alias registered
    # defensively per this app's established convention (see the
    # contact-requests routes above) since APPEND_SLASH=False means Django
    # never redirects a stray trailing slash on its own.
    path("conference/config", views.conference_config),
    path("conference/config/", views.conference_config),
]
