from django.apps import AppConfig


class CompaniesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.companies"
    verbose_name = "Компании"
    # URL-автодискавери (htqweb/urls.py) смонтирует аппку по этому префиксу
    # без правки htqweb/urls.py. Имя сервиса в реестре совпадает с app_label,
    # поэтому запись в APP_LABEL_TO_SERVICE не нужна.
    API_PREFIX = "api/companies/v1/"
