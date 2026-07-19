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
    # stray trailing slash on its own).
    path("files/", views.upload_file),
    path("files", views.upload_file),
]
