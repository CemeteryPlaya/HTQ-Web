from django.db import models

# Канонические имена сервисов платформы (совпадают с именами аппок,
# кроме исторических: approvals ↔ /api/requests/, mail ↔ /api/email/).
KNOWN_SERVICES = ["users", "hr", "tasks", "approvals", "cms",
                  "media", "mail", "messenger", "conference", "contracts",
                  "signoff"]


class ServiceStatus(models.Model):
    app_label = models.CharField(max_length=32, unique=True)
    enabled = models.BooleanField(default=True)
    message = models.CharField(max_length=200,
                               default="Сервис в данный момент недоступен")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Состояние сервиса"
        verbose_name_plural = "Состояния сервисов"
        db_table = "core_service_status"
