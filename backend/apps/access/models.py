"""Модель доступа: глобальный каталог ролей и его привязки к компаниям.

Все таблицы аппки живут в схеме ``public`` — роль заводится один раз на всю
группу (спека стадии 2, §1.3), поэтому ``apps.access`` НЕ входит в
``settings.TENANT_APPS``.

Компания хранится СЛАГОМ, а не внешним ключом. Соблазн поставить настоящий ключ
велик (обе таблицы в одной схеме, ссылочная целостность получалась бы бесплатно),
но ``Company`` принадлежит ``apps.companies``, а межаппных ForeignKey у платформы
нет — тот же инвариант, по которому ``hr.Employee.user_id`` обычный ``int``.
Слаг, а не ``id``, потому что разрешение прав получает из контекста запроса
именно слаг (``htqweb.tenancy.context.current_company``): ссылка по ``id``
стоила бы лишнего обращения в реестр на каждой проверке прав.

⚠️ ``search_path`` эти таблицы НЕ изолирует — они в ``public``. Изоляция держится
обязательным фильтром по ``company_slug`` в сервисном слое, и это единственная
её опора: забытый фильтр отдаёт права соседней компании, не выглядя ошибкой.
Сторож — ``apps/access/tests/test_guards.py``.
"""

from django.db import models


class Level(models.TextChoices):
    NONE = "none", "Нет доступа"
    READ = "read", "Чтение"
    WRITE = "write", "Запись"
    ADMIN = "admin", "Администрирование"


# Порядок сравнения уровней. Один источник истины на бэкенде; у фронта своя
# копия в src/api/access.ts — сравнение нужно и до сетевого запроса.
LEVEL_ORDER = {Level.NONE: 0, Level.READ: 1, Level.WRITE: 2, Level.ADMIN: 3}


class ScopeKind(models.TextChoices):
    COMPANY = "company", "Компания"
    DEPARTMENT = "department", "Отдел"
    SITE = "site", "Объект"


class Role(models.Model):
    """Набор прав, действующий во всех компаниях группы (правила 1 и 3).

    Ни веса, ни родителя у роли нет: иерархию несёт должность. Второе дерево
    на роли означало бы второй ответ на вопрос «кто кому подчинён».
    """

    code = models.SlugField(max_length=64, unique=True)
    title = models.CharField(max_length=255)
    # Служебные роли сидируются и не удаляются через API.
    is_system = models.BooleanField(default=False, db_default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Роль"
        verbose_name_plural = "Роли"
        ordering = ["title"]

    def __str__(self) -> str:
        return self.title


class RoleModulePermission(models.Model):
    """Уровень роли на один модуль. Отсутствие строки означает ``none``."""

    role = models.ForeignKey(Role, on_delete=models.CASCADE, related_name="permissions")
    # Значение из apps.core.models.KNOWN_SERVICES. Не choices: реестр модулей
    # меняется добавлением аппки, и миграция на каждое такое добавление
    # означала бы, что список живёт в двух местах.
    module = models.CharField(max_length=32)
    level = models.CharField(max_length=8, choices=Level.choices)

    class Meta:
        verbose_name = "Право роли"
        verbose_name_plural = "Права ролей"
        constraints = [
            models.UniqueConstraint(fields=["role", "module"], name="uniq_role_module"),
        ]

    def __str__(self) -> str:
        return f"{self.role_id}: {self.module}={self.level}"


class PositionRole(models.Model):
    """Роль, выданная должности компании — штатный путь выдачи прав (правило 2)."""

    company_slug = models.CharField(max_length=32, db_index=True)
    # Мягкая ссылка в apps.hr: должность лежит в схеме компании, FK поперёк
    # схем невозможен. Тот же приём, что у apps.signoff в маршрутах
    # согласования. id должностей нумеруются в каждой схеме независимо,
    # поэтому company_slug — обязательная часть ключа, а не уточнение.
    position_id = models.IntegerField()
    role = models.ForeignKey(Role, on_delete=models.CASCADE, related_name="position_links")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Роль должности"
        verbose_name_plural = "Роли должностей"
        constraints = [
            models.UniqueConstraint(
                fields=["company_slug", "position_id", "role"],
                name="uniq_position_role",
            ),
        ]
        indexes = [models.Index(fields=["company_slug", "position_id"])]

    def __str__(self) -> str:
        return f"{self.company_slug}/должность {self.position_id}: {self.role_id}"


class RoleAssignment(models.Model):
    """Личное назначение роли — исключение из штатного пути (спека §1.2).

    Закрывает то, чего должность закрыть не может: директор холдинга без
    кадровой карточки, исполняющий обязанности, временное расширение.
    """

    company_slug = models.CharField(max_length=32, db_index=True)
    user_id = models.IntegerField()
    role = models.ForeignKey(Role, on_delete=models.CASCADE, related_name="assignments")
    scope_kind = models.CharField(max_length=16, choices=ScopeKind.choices)
    scope_id = models.IntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Личное назначение роли"
        verbose_name_plural = "Личные назначения ролей"
        constraints = [
            # Два ЧАСТИЧНЫХ индекса вместо одного составного: в Postgres NULL
            # не равен NULL, поэтому обычная уникальность по scope_id
            # пропустила бы сколько угодно копий назначения на всю компанию.
            models.UniqueConstraint(
                fields=["company_slug", "user_id", "role", "scope_kind"],
                condition=models.Q(scope_id__isnull=True),
                name="uniq_assignment_unscoped",
            ),
            models.UniqueConstraint(
                fields=["company_slug", "user_id", "role", "scope_kind", "scope_id"],
                condition=models.Q(scope_id__isnull=False),
                name="uniq_assignment_scoped",
            ),
            # Область «компания» не имеет идентификатора, остальные — обязаны.
            # Проверка в БД, а не только в схеме запроса: django-admin и ORM
            # мимо вьюхи — такие же входы.
            models.CheckConstraint(
                condition=(
                    models.Q(scope_kind=ScopeKind.COMPANY, scope_id__isnull=True)
                    | (~models.Q(scope_kind=ScopeKind.COMPANY)
                       & models.Q(scope_id__isnull=False))
                ),
                name="assignment_scope_id_matches_kind",
            ),
        ]
        indexes = [models.Index(fields=["company_slug", "user_id"])]

    def __str__(self) -> str:
        return f"{self.company_slug}/пользователь {self.user_id}: {self.role_id}"
