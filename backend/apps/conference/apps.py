from django.apps import AppConfig


class ConferenceConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.conference"
    verbose_name = "Конференции"
    label = "conference"
    # URL-автодискавери (htqweb/urls.py): аппка сама объявляет свой префикс,
    # htqweb/urls.py её не знает. Имя `conference` уже было в
    # apps.core.models.KNOWN_SERVICES — оно резервировалось под SFU-стек,
    # у которого до сих пор не было своей Django-аппки. Теперь есть, и
    # ServiceGateMiddleware гейтит /api/conference/v1/ этим же флагом.
    API_PREFIX = "api/conference/v1/"
