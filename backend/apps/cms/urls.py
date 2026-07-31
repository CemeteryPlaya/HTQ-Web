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
    # News — frontend call sites (frontend/src/api/cms.ts): 'news/' (list,
    # create), 'news/{id}' with NO trailing slash (get/patch/delete),
    # 'news/by-slug/{slug}' with no trailing slash. Trailing-slash aliases on
    # the detail routes are registered defensively, same convention as the
    # contact-requests routes above (APPEND_SLASH=False never redirects a
    # stray trailing slash on its own).
    path("news/", views.news_collection),
    path("news/by-slug/<str:slug>", views.news_by_slug),
    path("news/by-slug/<str:slug>/", views.news_by_slug),
    # Более специфичный роут — ДО общего news/<id> (у Django они не
    # пересекаются, но конвенция репо «специфичное прежде общего»).
    path("news/<int:news_id>/translate", views.translate_news),
    path("news/<int:news_id>/translate/", views.translate_news),
    path("news/<int:news_id>", views.news_detail),
    path("news/<int:news_id>/", views.news_detail),
    # Categories — frontend call sites: 'categories/' (list, create),
    # 'categories/{id}' with no trailing slash (patch/delete). Trailing-slash
    # alias registered defensively per the same convention.
    path("categories/", views.categories_collection),
    path("categories/<int:category_id>", views.category_detail),
    path("categories/<int:category_id>/", views.category_detail),
    # Tags — frontend call sites: 'tags/' (list, create), 'tags/{id}' with no
    # trailing slash (patch/delete). Trailing-slash alias registered
    # defensively per the same convention.
    path("tags/", views.tags_collection),
    path("tags/<int:tag_id>", views.tag_detail),
    path("tags/<int:tag_id>/", views.tag_detail),
]
