from django.apps import AppConfig


class MediaFilesConfig(AppConfig):
    default_auto_field = "django.db.models.AutoField"
    name = "apps.media_files"
    label = "media_files"
    # URL-автодискавери (htqweb/urls.py, PLAN.md §4.1). Префикс — по URL
    # (media), а не по app_label (media_files) или сервису.
    API_PREFIX = "api/media/v1/"
