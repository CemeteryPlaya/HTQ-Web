"""Модели домена hr — порт services/hr/app/models/.

План и решения: docs/plans/2026-07-20-hr-domain.md

Имена таблиц — дефолтные Django (решение D2): hr_department, hr_position, …
Старые имена (hr_departments, …) живут только в карте ETL фазы 10.
"""

from django.db import models
from django.db.models.functions import Now


class HrBase(models.Model):
    """Порт services/hr/app/models/base.py::BaseModel.

    created_at/updated_at — NOT NULL с СЕРВЕРНЫМ дефолтом (в исходнике
    server_default=func.now()). db_default обязателен: без него вставка мимо
    ORM (ETL, raw SQL) упадёт на NOT NULL — именно так в фазе 1 потеряли
    19 серверных дефолтов. auto_now воспроизводит onupdate=func.now().
    """

    created_at = models.DateTimeField(db_default=Now())
    updated_at = models.DateTimeField(db_default=Now(), auto_now=True)

    class Meta:
        abstract = True


class UnitType(models.TextChoices):
    DEPARTMENT = "department", "Отдел"
    DIVISION = "division", "Управление"
    GROUP = "group", "Группа"


class EmployeeStatus(models.TextChoices):
    """Полный набор из КОНТРАКТА API, а не из комментария к модели.

    services/hr/app/models/employee.py комментирует поле как
    ``active | inactive | terminated``, но реальный контракт —
    ``schemas/employee.py::EmployeeBase.status`` с
    ``pattern="^(active|inactive|terminated|suspended|pending|rejected)$"``:
    клиент вправе прислать все шесть, и колонка (String(20) без constraint)
    их принимает. Сузить список здесь — значит соврать в админке и сломать
    любую будущую валидацию, поэтому переносим контрактный набор целиком.
    """

    ACTIVE = "active", "Работает"
    INACTIVE = "inactive", "Неактивен"
    TERMINATED = "terminated", "Уволен"
    SUSPENDED = "suspended", "Приостановлен"
    PENDING = "pending", "На согласовании"
    REJECTED = "rejected", "Отклонён"


class Department(HrBase):
    name = models.CharField(max_length=255, unique=True)
    # D1: в исходнике это String(500) с обычным индексом, а НЕ PG-ltree
    # (комментарий «ltree stored as plain text» там вводит в заблуждение —
    # расширение не подключено). Иерархия — строковый путь вида "it.dev";
    # предки вычисляются как префиксы, см. interface.org_ancestors.
    path = models.CharField(max_length=500, unique=True)
    description = models.TextField(null=True, blank=True)
    # D3: циклический FK (в исходнике use_alter=True). Поле nullable, поэтому
    # Django-автодетектор сам разложит его на CreateModel + AddField.
    manager = models.ForeignKey(
        "hr.Employee",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="managed_department",
    )
    is_active = models.BooleanField(default=True, db_default=True)
    unit_type = models.CharField(
        max_length=20,
        choices=UnitType.choices,
        default=UnitType.DEPARTMENT,
        db_default=UnitType.DEPARTMENT.value,
    )

    def __str__(self) -> str:
        return self.name


class Position(HrBase):
    title = models.CharField(max_length=255, unique=True)
    department = models.ForeignKey(
        Department, on_delete=models.CASCADE, related_name="positions"
    )
    grade = models.IntegerField(default=1, db_default=1)  # 1–10
    description = models.TextField(null=True, blank=True)
    requirements = models.JSONField(null=True, blank=True)
    is_active = models.BooleanField(default=True, db_default=True)
    # Меньший вес = выше в иерархии (0 = верх). Глобально уникален.
    weight = models.IntegerField(unique=True, default=100, db_default=100)
    # Кэш из hr_levelthreshold; пересчитывается при смене weight.
    level = models.IntegerField(default=2, db_default=2, db_index=True)
    # Системные должности — базовые оргединицы (сидируются): их нельзя
    # переименовать/удалить через UI, но вес/отдел/права редактируемы.
    is_system = models.BooleanField(default=False, db_default=False, db_index=True)
    # Явная матрица прав; когда задана, приоритетнее эвристики по названию
    # должности (app/auth/hr_access.py в исходнике).
    # Форма: {"hr_level": "junior|middle|senior|lead", "permissions": [str, ...]}
    permissions = models.JSONField(null=True, blank=True)

    def __str__(self) -> str:
        return self.title


class Employee(HrBase):
    # D7: связь с apps.users — обычный int, а НЕ межаппный FK (межаппные FK
    # запрещены). Данные аккаунта берутся через apps.users.interface.
    user_id = models.IntegerField(null=True, blank=True, unique=True)
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    middle_name = models.CharField(max_length=100, null=True, blank=True)
    email = models.CharField(max_length=255, unique=True)
    phone = models.CharField(max_length=20, null=True, blank=True)
    department = models.ForeignKey(
        Department, on_delete=models.PROTECT, related_name="employees"
    )
    position = models.ForeignKey(
        Position, on_delete=models.PROTECT, related_name="employees"
    )
    hire_date = models.DateField()
    termination_date = models.DateField(null=True, blank=True)
    status = models.CharField(
        max_length=20,
        choices=EmployeeStatus.choices,
        default=EmployeeStatus.ACTIVE,
        db_default=EmployeeStatus.ACTIVE.value,
    )
    avatar_url = models.CharField(max_length=500, null=True, blank=True)
    bio = models.TextField(null=True, blank=True)
    is_deleted = models.BooleanField(default=False, db_default=False)  # soft delete

    def __str__(self) -> str:
        return f"{self.last_name} {self.first_name}"


class LevelThreshold(HrBase):
    """Настраиваемое отображение диапазонов веса в уровни иерархии."""

    level_number = models.IntegerField(unique=True)
    weight_from = models.IntegerField()
    weight_to = models.IntegerField()
    label = models.CharField(max_length=100, null=True, blank=True)
    color = models.CharField(max_length=7, null=True, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(weight_from__lte=models.F("weight_to")),
                name="ck_threshold_range",
            ),
            models.CheckConstraint(
                condition=models.Q(level_number__gte=1),
                name="ck_threshold_level_positive",
            ),
        ]

    def __str__(self) -> str:
        return f"L{self.level_number} ({self.weight_from}–{self.weight_to})"


class PositionWeightAudit(models.Model):
    """Append-only лог изменений веса/уровня должности.

    Порт services/hr/app/models/position_weight_audit.py. Не наследует
    HrBase — у исходника нет created_at/updated_at, только changed_at
    (server_default=func.now()). PK — BigInteger в исходнике (высокообъёмный
    аппенд-лог), поэтому BigAutoField, а не дефолтный AutoField аппки.
    Таблица — дефолтное имя Django: hr_positionweightaudit.
    """

    id = models.BigAutoField(primary_key=True)
    # db_index=False: FK по умолчанию создаёт отдельный индекс на position_id,
    # но составной indexes=[(position, changed_at)] ниже уже покрывает запросы
    # по одному position_id своим левым префиксом. Исходник имеет РОВНО один
    # (составной) индекс — не плодим лишний (ревью 100e2af, Minor #2).
    position = models.ForeignKey(
        Position, on_delete=models.CASCADE, related_name="weight_audits", db_index=False,
    )
    old_weight = models.IntegerField(null=True, blank=True)
    new_weight = models.IntegerField(null=True, blank=True)
    old_level = models.IntegerField(null=True, blank=True)
    new_level = models.IntegerField(null=True, blank=True)
    changed_by = models.IntegerField(null=True, blank=True)
    changed_at = models.DateTimeField(db_default=Now())
    reason = models.CharField(max_length=64, null=True, blank=True)

    class Meta:
        # Составной индекс (position_id, changed_at) — порт
        # Index("ix_hr_position_weight_audit_position", "position_id", "changed_at").
        # Имя не задаём явно: Django сам генерирует детерминированное короткое
        # имя (см. max_name_length()) — не привязываемся к имени исходника,
        # у которого другое имя таблицы (hr_position_weight_audit vs
        # дефолтное hr_positionweightaudit здесь).
        indexes = [models.Index(fields=["position", "changed_at"])]

    def __str__(self) -> str:
        return f"Position #{self.position_id}: {self.old_weight}->{self.new_weight}"


class AuditLog(HrBase):
    """Аудит-лог HR-мутаций — порт services/hr/app/models/audit_log.py.

    Таблица — дефолтное имя Django: hr_auditlog (а не hr_audit_log исходника,
    решение D2, как и у остальных моделей домена).

    D10 — ``changed_by`` НЕ FK, хотя в исходнике объявлен как
    ``ForeignKey("hr_employees.id")``. Реальное значение, которое туда
    пишется — ``TokenPayload.user_id`` (id платформенного пользователя из
    JWT: ``employee_service.py`` везде передаёт ``changed_by_id=
    current_user.user_id``), а не PK строки ``Employee`` — то же
    ID-пространство, что и у ``Employee.user_id`` (решение D7), не
    пространство PK ``hr_employees``. FK на несовпадающее пространство ID
    означал бы, что Postgres откатывает КАЖДОЕ создание/изменение/удаление/
    перевод сотрудника всякий раз, когда действующий пользователь не
    оказался (случайно, по числовому совпадению) той же строкой в
    ``hr_employees`` — то есть почти всегда, а ``audit_service.log(...)`` в
    исходнике нигде не обёрнут в try/except (мутация обязана падать вместе
    с записью аудита). Этот путь не покрыт ни одним интеграционным тестом
    исходника (``test_permission_enforcement.py`` проверяет только матрицу
    прав), а аналогичное по смыслу поле ``PositionWeightAudit.changed_by``
    там же в исходнике уже сделано простым ``Integer`` без FK — тот же
    паттерн, применённый последовательно. Портируем как простой
    ``IntegerField`` (NOT NULL, как и в исходнике), без ``db_index``: ни
    сама колонка, ни исходник её отдельно не индексируют — только составной
    индекс ниже.
    """

    entity_type = models.CharField(max_length=50)  # employee | department | ...
    entity_id = models.IntegerField()
    action = models.CharField(max_length=20)  # create | update | delete
    old_values = models.JSONField(null=True, blank=True)
    new_values = models.JSONField(null=True, blank=True)
    changed_by = models.IntegerField()
    ip_address = models.CharField(max_length=45, null=True, blank=True)
    user_agent = models.CharField(max_length=500, null=True, blank=True)

    class Meta:
        # Порт Index("ix_audit_log_entity", "entity_type", "entity_id") —
        # единственный индекс исходника на этой таблице.
        indexes = [models.Index(fields=["entity_type", "entity_id"])]

    def __str__(self) -> str:
        return f"<AuditLog(id={self.id}, entity={self.entity_type}:{self.entity_id}, action='{self.action}')>"


class RelationType(models.TextChoices):
    DIRECT = "direct", "Прямое"
    FUNCTIONAL = "functional", "Функциональное"
    PROJECT = "project", "Проектное"


class ReportingRelation(HrBase):
    """Ячейка матрицы подчинения — порт services/hr/app/models/reporting_relation.py.

    Таблица — дефолтное имя Django: hr_reportingrelation (не hr_reporting_relations
    исходника, решение D2, как и у остальных моделей домена).

    Оба FK — ``on_delete=CASCADE`` и БЕЗ ``db_index=False``: в отличие от
    ``PositionWeightAudit.position`` (там лишний индекс убран, т.к. составной
    индекс уже покрывал запросы своим левым префиксом), у исходника здесь РОВНО
    два независимых индекса (``Index("ix_reporting_superior", ...)`` и
    ``Index("ix_reporting_subordinate", ...)`` — SQLAlchemy FK индекс не создаёт
    сам по себе). Django FK, наоборот, индексирует колонку по умолчанию — так
    дефолт Django воспроизводит оба индекса исходника без явного ``indexes=``.
    """

    superior_position = models.ForeignKey(
        Position, on_delete=models.CASCADE, related_name="subordinate_relations",
    )
    subordinate_position = models.ForeignKey(
        Position, on_delete=models.CASCADE, related_name="superior_relations",
    )
    relation_type = models.CharField(
        max_length=20,
        choices=RelationType.choices,
        default=RelationType.DIRECT,
        db_default=RelationType.DIRECT.value,
    )
    effective_from = models.DateField()
    effective_to = models.DateField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["superior_position", "subordinate_position", "relation_type"],
                name="uq_reporting_relation",
            ),
            models.CheckConstraint(
                condition=~models.Q(superior_position=models.F("subordinate_position")),
                name="ck_no_self_relation",
            ),
            models.CheckConstraint(
                condition=models.Q(relation_type__in=list(RelationType.values)),
                name="ck_relation_type",
            ),
        ]

    def __str__(self) -> str:
        return f"<ReportingRelation(sup={self.superior_position_id}, sub={self.subordinate_position_id}, type='{self.relation_type}')>"


class OrgSettings(models.Model):
    """Key-value настройки поведения оргструктуры.

    D5: в исходнике наследует Base, а НЕ BaseModel — поэтому здесь
    models.Model и НЕТ created_at (есть только updated_at).
    """

    key = models.CharField(max_length=100, unique=True)
    value = models.CharField(max_length=500)
    description = models.TextField(null=True, blank=True)
    updated_at = models.DateTimeField(db_default=Now())

    def __str__(self) -> str:
        return f"{self.key}={self.value!r}"
