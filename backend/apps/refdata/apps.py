from django.apps import AppConfig


class RefdataConfig(AppConfig):
    default_auto_field = "django.db.models.AutoField"
    name = "apps.refdata"
    verbose_name = "Справочники"
    # Общие справочники модуля БЗО (страны, валюты, курсы, НДС, МРП, единицы
    # измерения, статьи): одна копия на группу в схеме public, правят только
    # роли управляющей компании (мастер-план, D-03).
    API_PREFIX = "api/refdata/v1/"
