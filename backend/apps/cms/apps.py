from django.apps import AppConfig


class CmsConfig(AppConfig):
    default_auto_field = "django.db.models.AutoField"
    name = "apps.cms"
    # URL-автодискавери (htqweb/urls.py, PLAN.md §4.1).
    API_PREFIX = "api/cms/v1/"
