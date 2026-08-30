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


class RolePermission(models.Model):
    """Глубина роли на один узел реестра функций (``apps.access.registry``).

    Узел — путь вида ``hr``, ``hr.employees`` или ``hr.employees.salary``.
    Отсутствие строки НЕ означает «нет доступа»: не заданный явно узел
    наследует глубину ближайшего предка, у которого она задана (§1.8 спеки).
    Пустой набор флагов, наоборот, означает именно запрет — им перекрывают
    унаследованное разрешение.

    Флаги независимы и хранятся четырьмя колонками, а не битовой маской:
    их видно в django-admin и в SQL глазами, а маску пришлось бы расшифровывать
    в голове каждый раз, когда права разбирают по живой базе.
    """

    role = models.ForeignKey(Role, on_delete=models.CASCADE, related_name="permissions")
    node = models.CharField(max_length=128)

    can_view = models.BooleanField(default=False, db_default=False)
    can_create = models.BooleanField(default=False, db_default=False)
    can_edit = models.BooleanField(default=False, db_default=False)
    can_delete = models.BooleanField(default=False, db_default=False)

    class Meta:
        verbose_name = "Глубина роли"
        verbose_name_plural = "Глубина ролей"
        constraints = [
            models.UniqueConstraint(fields=["role", "node"], name="uniq_role_node"),
        ]
        indexes = [models.Index(fields=["node"])]

    @property
    def flags(self) -> frozenset[str]:
        from apps.access import depth

        return frozenset(
            flag for flag, on in (
                (depth.VIEW, self.can_view),
                (depth.CREATE, self.can_create),
                (depth.EDIT, self.can_edit),
                (depth.DELETE, self.can_delete),
            ) if on
        )

    def set_flags(self, flags) -> None:
        from apps.access import depth

        self.can_view = depth.VIEW in flags
        self.can_create = depth.CREATE in flags
        self.can_edit = depth.EDIT in flags
        self.can_delete = depth.DELETE in flags

    def __str__(self) -> str:
        return f"{self.role_id}: {self.node} = {sorted(self.flags) or 'нет доступа'}"


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
