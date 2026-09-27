"""Маршруты ``/api/files/v1/`` (URL-автодискавери, ``FilesConfig.API_PREFIX``).

``APPEND_SLASH=False`` — каждое написание регистрируется явно. Литеральные
``types`` — первыми; с маршрутами владельца они и так не пересекаются
(у тех третий сегмент — ``files``), но порядок держит соглашение репозитория.

``<owner_type>`` — ключ владельца из реестра вида ``<аппка>.<модель>``,
``<owner_id>`` — ключ его строки: целое у старых владельцев, UUID у
документов модуля БЗО. Строкой — тип ключа знает владелец
(``OwnerEntry.native_id``), неподходящий ключ — 404, а не 500.
"""

from django.urls import path

from . import views

_OWNER = "<str:owner_type>/<str:owner_id>/files"
_DOC = f"{_OWNER}/<uuid:document_id>"

urlpatterns = [
    path("types", views.types_collection),
    path("types/", views.types_collection),
    path("types/<str:code>", views.type_detail),
    path("types/<str:code>/", views.type_detail),

    path(_OWNER, views.owner_files),
    path(f"{_OWNER}/", views.owner_files),
    path(_DOC, views.document_detail),
    path(f"{_DOC}/", views.document_detail),
    path(f"{_DOC}/versions", views.document_versions),
    path(f"{_DOC}/versions/", views.document_versions),
    path(f"{_DOC}/versions/<int:file_id>/link", views.version_link),
    path(f"{_DOC}/versions/<int:file_id>/link/", views.version_link),
]
