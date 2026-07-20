from django.urls import path

from . import views

urlpatterns = [
    # Frontend call sites audited (task 3.2 brief): frontend/src/api/media.ts
    # (mediaApi.upload → `media/v1/files/`), frontend/src/pages/AdminNews.tsx
    # (`${API_ENDPOINTS.mediaFiles}/`), frontend/src/components/news/
    # NewsEditor.tsx (Jodit uploader, `'/' + API_ENDPOINTS.mediaFiles + '/'`)
    # — all three POST to the trailing-slash spelling. The no-slash alias is
    # registered defensively, same convention as apps/cms/urls.py's
    # contact-requests/news routes (APPEND_SLASH=False never redirects a
    # stray trailing slash on its own). GET on either spelling lists files
    # (admin only, task 3.3) — see ``views.files_collection``.
    path("files/", views.files_collection),
    path("files", views.files_collection),
    # `{file_id}/sign` (POST) and `{file_id}/{variant}` (GET) share one path
    # shape in the FastAPI source, disambiguated by method — reproduced by
    # one dispatcher (``views.file_tail_dispatch``) since Django's `path()`
    # doesn't route on method. MUST be registered before the bare
    # `<uuid:file_id>` entry below (Django tries patterns top-to-bottom;
    # both could otherwise never be reached, but keeping the more specific
    # 2-segment pattern first is the safer/clearer order).
    path("files/<uuid:file_id>/<str:tail>", views.file_tail_dispatch),
    path("files/<uuid:file_id>", views.download_file),
    # Catch-all: raw storage-key serving for files with no FileMetadata row
    # (currently: avatars — see ``views.serve_raw_key``'s docstring). MUST
    # be last — a genuine UUID segment always matches the `<uuid:file_id>`
    # entry above first; this only engages for keys containing `/` (or any
    # other non-UUID-shaped segment) that fell through every route above.
    path("files/<path:file_key>", views.serve_raw_key),
]
