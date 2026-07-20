from django.apps import apps as django_apps
from django.contrib import admin
from django.urls import include, path
from django.utils.module_loading import module_has_submodule

urlpatterns = [
    path("django-admin/", admin.site.urls),   # /admin занят React-страницами SPA
    path("", include("apps.core.urls")),
]

# URL-автодискавери доменных аппок (PLAN.md §4.1) — снимает этот файл как
# точку конфликта параллельных потоков. Каждая apps.* аппка, объявившая в
# своём AppConfig атрибут API_PREFIX и имеющая модуль urls, монтируется под
# этим префиксом автоматически. Добавление новой доменной аппки НЕ требует
# правки htqweb/urls.py — достаточно API_PREFIX в её apps.py.
#
# apps.core сюда НЕ попадает намеренно: у него нет API_PREFIX (свой префикс
# api/core/v1/ он объявляет внутри apps/core/urls.py) и он смонтирован выше
# в корень "". Порядок монтирования не важен: все API_PREFIX различны.
for _config in django_apps.get_app_configs():
    _api_prefix = getattr(_config, "API_PREFIX", None)
    if _api_prefix and module_has_submodule(_config.module, "urls"):
        urlpatterns.append(path(_api_prefix, include(f"{_config.name}.urls")))
