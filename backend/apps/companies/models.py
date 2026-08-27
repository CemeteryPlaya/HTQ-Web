from django.core.validators import RegexValidator
from django.db import models
from django.db.models.functions import Now

# slug одновременно служит поддоменом и суффиксом имени схемы, поэтому набор
# символов сужен до того, что безопасно и там, и там: DNS-метка не допускает
# подчёркиваний и заглавных, идентификатор Postgres не допускает дефисов
# (замена на "_" делается в htqweb.tenancy.context.schema_for).
SLUG_VALIDATOR = RegexValidator(
    r"^[a-z0-9]([a-z0-9-]{0,30}[a-z0-9])?$",
    "Только строчные латинские буквы, цифры и дефис; не начинается и не "
    "заканчивается дефисом; до 32 символов.",
)


class CompanyKind(models.TextChoices):
    HOLDING = "holding", "Холдинг"
    REGIONAL = "regional", "Региональная"
    SERVICE = "service", "Сервисная"


class CompanyStatus(models.TextChoices):
    ACTIVE = "active", "Действует"
    ARCHIVED = "archived", "В архиве"


class Company(models.Model):
    """Юридическое лицо группы. Владеет собственной схемой Postgres.

    Дерево владения (``parent``) и граф оказания услуг
    (``CompanyServiceLink``) — РАЗНЫЕ структуры и намеренно не сведены в
    одну: сервисная компания подчинена холдингу, но обслуживает несколько
    региональных сразу.
    """

    slug = models.CharField(max_length=32, unique=True, validators=[SLUG_VALIDATOR])
    name = models.CharField(max_length=255)
    kind = models.CharField(max_length=16, choices=CompanyKind.choices)
    country = models.CharField(max_length=2, blank=True, default="", db_default="")
    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT,
        related_name="children",
    )
    status = models.CharField(
        max_length=16, choices=CompanyStatus.choices,
        default=CompanyStatus.ACTIVE, db_default=CompanyStatus.ACTIVE.value,
        db_index=True,
    )
    # Заполняется при банкротстве (подпроект 4). Здесь только объявлено,
    # чтобы схема не менялась вторично, когда до него дойдут руки.
    successor = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="predecessors",
    )
    archived_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_default=Now())
    updated_at = models.DateTimeField(auto_now=True, db_default=Now())

    class Meta:
        verbose_name = "Компания"
        verbose_name_plural = "Компании"
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class CompanyServiceLink(models.Model):
    """«Кто кому оказывает услуги» — граф ТМЗ, отдельный от дерева владения."""

    provider = models.ForeignKey(
        Company, on_delete=models.CASCADE, related_name="provided_services",
    )
    consumer = models.ForeignKey(
        Company, on_delete=models.CASCADE, related_name="consumed_services",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_default=Now())

    class Meta:
        verbose_name = "Связь по услугам"
        verbose_name_plural = "Связи по услугам"
        constraints = [
            models.UniqueConstraint(
                fields=["provider", "consumer"], name="uniq_service_link",
            ),
            models.CheckConstraint(
                condition=~models.Q(provider=models.F("consumer")),
                name="service_link_not_self",
            ),
        ]


class CompanyMembership(models.Model):
    """Право пользователя работать в компании.

    ``user_id`` — обычный int, а НЕ FK: межаппные ForeignKey запрещены
    инвариантом платформы (образец — apps.hr.models.Employee.user_id).
    """

    user_id = models.IntegerField(db_index=True)
    company = models.ForeignKey(
        Company, on_delete=models.CASCADE, related_name="memberships",
    )
    is_default = models.BooleanField(default=False, db_default=False)
    created_at = models.DateTimeField(auto_now_add=True, db_default=Now())

    class Meta:
        verbose_name = "Членство в компании"
        verbose_name_plural = "Членство в компаниях"
        constraints = [
            models.UniqueConstraint(
                fields=["user_id", "company"], name="uniq_membership",
            ),
        ]


class CompanyModule(models.Model):
    """Второй, независимый слой рубильника поверх apps.core.ServiceStatus.

    ServiceStatus гасит аппку на ВСЕЙ платформе; эта таблица — в одной
    компании. Семантика объединения (см. apps.core.services.require_service):
    глобально выключено -> 503 везде; глобально включено, у компании
    выключено -> 503 только там. Отсутствие строки означает «включено».
    """

    company = models.ForeignKey(
        Company, on_delete=models.CASCADE, related_name="modules",
    )
    app_label = models.CharField(max_length=32)
    enabled = models.BooleanField(default=True, db_default=True)
    message = models.CharField(
        max_length=200, default="Модуль недоступен для этой компании",
        db_default="Модуль недоступен для этой компании",
    )
    updated_at = models.DateTimeField(auto_now=True, db_default=Now())

    class Meta:
        verbose_name = "Модуль компании"
        verbose_name_plural = "Модули компаний"
        constraints = [
            models.UniqueConstraint(
                fields=["company", "app_label"], name="uniq_company_module",
            ),
        ]


class CompanySchemaVersion(models.Model):
    """Фактическая и целевая версия миграций схемы компании по каждой аппке.

    Существует, чтобы отставание схемы было видно ДО того, как проявится
    500-й ошибкой: разные компании обновляются с разной скоростью, и это
    штатный режим, а не авария.
    """

    company = models.ForeignKey(
        Company, on_delete=models.CASCADE, related_name="schema_versions",
    )
    app_label = models.CharField(max_length=32)
    applied_migration = models.CharField(max_length=255, blank=True, default="", db_default="")
    target_migration = models.CharField(max_length=255, blank=True, default="", db_default="")
    last_run_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True, default="", db_default="")

    class Meta:
        verbose_name = "Версия схемы компании"
        verbose_name_plural = "Версии схем компаний"
        constraints = [
            models.UniqueConstraint(
                fields=["company", "app_label"], name="uniq_schema_version",
            ),
        ]
