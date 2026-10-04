from django.db import models

# Канонические имена сервисов платформы (совпадают с именами аппок,
# кроме исторических: approvals ↔ /api/requests/, mail ↔ /api/email/).
KNOWN_SERVICES = ["users", "hr", "tasks", "approvals", "cms",
                  "media", "mail", "messenger", "conference", "contracts",
                  "signoff", "companies", "access", "files",
                  "project", "refdata", "notifications", "bpp"]

# Подмодули с собственным рубильником: подмодуль → родительский сервис из
# KNOWN_SERVICES (вложенность одна). Подмодуль гаснет вместе с родителем
# (apps.core.services.disabled_layer). В реестр прав подмодули не входят
# намеренно: права выдаются на модуль целиком, подмодуль — только
# выключатель, и редактор ролей не должен показывать пустые модули.
KNOWN_SUBMODULES: dict[str, str] = {
    "bpp_budget": "bpp",
    "bpp_requests": "bpp",        # заявки и план закупок
    "bpp_agreements": "bpp",
    "bpp_invoices": "bpp",
    "bpp_bank": "bpp",
    "bpp_alternatives": "bpp",    # альтернативы и KPI
    "bpp_accountable": "bpp",
}


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
