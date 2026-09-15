from django.core.validators import RegexValidator
from django.db import models
from django.db.models.functions import Now

# slug одновременно служит поддоменом и суффиксом имени схемы, поэтому набор
# символов сужен до того, что безопасно и там, и там: DNS-метка не допускает
# подчёркиваний и заглавных, идентификатор Postgres не допускает дефисов
# (замена на "_" делается в htqweb.tenancy.context.schema_for).
#
# Первый символ — ТОЛЬКО буква, а не [a-z0-9], как было раньше: шлюз
# (infra/nginx/default.conf, server_name-регулярка) распознаёт компанию по
# поддомену через ``(?<company>[a-z][a-z0-9-]*)`` именно затем, чтобы отсечь
# IP-адреса (первая метка "192.168..." начинается с цифры и не должна
# читаться как компания). До этой правки валидатор пропускал slug вида
# "7hills" — компания заводилась в реестре успешно, но nginx её поддомен
# никогда не матчил регуляркой, то есть заголовок X-HTQ-Company для неё не
# ставился НИКОГДА: компания молча недостижима с первого дня, без единой
# ошибки при создании.
#
# "www" запрещён отдельно (полное совпадение, а не префикс — "www2" и
# "www-team" валидны): тот же default.conf исключает его негативным
# lookahead'ом ``(?!www\.)`` как самый частый зарезервированный поддомен.
SLUG_VALIDATOR = RegexValidator(
    r"^(?!www$)[a-z]([a-z0-9-]{0,30}[a-z0-9])?$",
    "Только строчные латинские буквы, цифры и дефис; первый символ — буква; "
    "не заканчивается дефисом; до 32 символов; \"www\" зарезервирован.",
)


class CompanyKind(models.TextChoices):
    """Вид компании по утверждённой оргструктуре группы (10.09.2026).

    Холдинг владеет долями, ДО — строительная (Hi-Tech Qazaqstan), IT
    (Hi-Tech Systems) и сервисная (Kazakhstan Engineering Group).
    """

    HOLDING = "holding", "Холдинг"
    CONSTRUCTION = "construction", "Строительная"
    IT = "it", "IT-компания"
    SERVICE = "service", "Сервисная"
    # Значение первой редакции дизайна (региональные компании UZ/KG, которых в
    # утверждённой структуре нет). Принимается, пока строка с ним есть в бою:
    # единственная компания получает kind правкой через API блока A, после
    # чего значение снимается отдельным contract-шагом. Убрать его сейчас —
    # значит уронить валидацию существующей строки реестра.
    REGIONAL = "regional", "Региональная (устар.)"


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
    # Задача 7 блока C, решение заказчика 4: видимость списка внешних
    # держателей прав (сотрудников вышестоящих компаний, чья обслуживающая
    # должность несёт им права здесь) — настройка КОМПАНИИ, а не выбор её
    # собственного администратора и не «всегда показывать». Правит её только
    # платформенный администратор — тем же гейтом, что и остальные поля
    # реестра (``CompanyItemView.patch::deny_unless_platform_admin``), новый
    # гейт не заводится. Включено по умолчанию: скрывать по умолчанию значило
    # бы прятать сам факт доступа от той компании, чьи данные читают.
    show_external_holders = models.BooleanField(default=True, db_default=True)
    created_at = models.DateTimeField(auto_now_add=True, db_default=Now())
    updated_at = models.DateTimeField(auto_now=True, db_default=Now())

    class Meta:
        verbose_name = "Компания"
        verbose_name_plural = "Компании"
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name

    @property
    def parent_slug(self) -> str | None:
        """Slug вышестоящей компании — для схем ответа (``from_attributes``)."""
        return self.parent.slug if self.parent_id else None


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
