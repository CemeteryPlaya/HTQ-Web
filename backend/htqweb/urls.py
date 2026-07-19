from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("django-admin/", admin.site.urls),   # /admin занят React-страницами SPA
    path("", include("apps.core.urls")),
    path("api/cms/v1/", include("apps.cms.urls")),
    path("api/users/v1/", include("apps.users.urls")),
    # По мере миграции фаз сюда добавляются:
    # ...
]
