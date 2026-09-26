from django.apps import AppConfig


class NotificationsConfig(AppConfig):
    default_auto_field = "django.db.models.AutoField"
    name = "apps.notifications"
    verbose_name = "Уведомления"
    # Хранимый центр уведомлений платформы (колокольчик, e-mail, Telegram),
    # схема public (мастер-план, D-24). Ручки — самообслуживание (свои
    # уведомления и свои каналы), поэтому access_functions.py у аппки нет.
    API_PREFIX = "api/notifications/v1/"
