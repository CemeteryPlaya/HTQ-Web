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


class VacancyStatus(models.TextChoices):
    OPEN = "open", "Открыта"
    CLOSED = "closed", "Закрыта"
    ON_HOLD = "on_hold", "Приостановлена"


class ApplicationStatus(models.TextChoices):
    NEW = "new", "Новый"
    REVIEWED = "reviewed", "Рассмотрен"
    INTERVIEW = "interview", "Собеседование"
    OFFER = "offer", "Оффер"
    REJECTED = "rejected", "Отклонён"
    HIRED = "hired", "Принят"


class _CurrentDate(models.Func):
    """``CURRENT_DATE`` без скобок — Postgres не принимает ``CURRENT_DATE()``.

    Порт ``server_default=func.current_date()`` (services/hr/app/models/vacancy.py
    ::Vacancy.opened_at) — тот же приём, что и ``Now()`` для created_at/updated_at,
    только для колонки типа DATE, для которой Django не даёт готового хелпера.
    """

    function = "CURRENT_DATE"
    template = "%(function)s"
    output_field = models.DateField()


class Vacancy(HrBase):
    """Порт services/hr/app/models/vacancy.py.

    Таблица — дефолтное имя Django: hr_vacancy (не hr_vacancies исходника,
    решение D2, как и у остальных моделей домена).
    """

    title = models.CharField(max_length=255)
    # FK NOT NULL без явного ondelete в исходнике -> PROTECT (тот же выбор,
    # что для Employee.department/position, см. docs/plans/2026-07-20-hr-domain.md
    # «Открытые вопросы» #2).
    department = models.ForeignKey(
        Department, on_delete=models.PROTECT, related_name="vacancies",
    )
    position = models.ForeignKey(
        Position, on_delete=models.PROTECT, related_name="vacancies",
    )
    # Text NOT NULL с клиентским default="" в исходнике (не server_default) —
    # db_default всё равно ставим (та же практика, что и у is_active/weight/…
    # в этом файле): защищает вставки мимо ORM от NOT NULL violation.
    description = models.TextField(default="", db_default="", blank=True)
    requirements = models.TextField(default="", db_default="", blank=True)
    status = models.CharField(
        max_length=20,
        choices=VacancyStatus.choices,
        default=VacancyStatus.OPEN,
        db_default=VacancyStatus.OPEN.value,
    )
    opened_at = models.DateField(db_default=_CurrentDate())
    closed_at = models.DateField(null=True, blank=True)
    # Nullable FK без явного ondelete в исходнике -> SET_NULL (тот же выбор,
    # что для Department.manager -> Employee).
    assigned_recruiter = models.ForeignKey(
        Employee, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="assigned_vacancies",
    )

    def __str__(self) -> str:
        return f"{self.title} ({self.status})"


class Application(HrBase):
    """Отклик кандидата — порт services/hr/app/models/application.py.

    Таблица — дефолтное имя Django: hr_application (не hr_applications
    исходника, решение D2, как и у остальных моделей домена).
    """

    vacancy = models.ForeignKey(
        Vacancy, on_delete=models.PROTECT, related_name="applications",
    )
    candidate_name = models.CharField(max_length=255)
    candidate_email = models.CharField(max_length=255)
    candidate_phone = models.CharField(max_length=20, null=True, blank=True)
    resume_url = models.CharField(max_length=500, null=True, blank=True)
    cover_letter = models.TextField(null=True, blank=True)
    status = models.CharField(
        max_length=30,
        choices=ApplicationStatus.choices,
        default=ApplicationStatus.NEW,
        db_default=ApplicationStatus.NEW.value,
    )
    applied_at = models.DateTimeField(db_default=Now())
    notes = models.TextField(null=True, blank=True)

    def __str__(self) -> str:
        return f"{self.candidate_name} -> vacancy #{self.vacancy_id} ({self.status})"


# ═══════════════════════════════════════════════════════════════════════════
#  docs: Document (реляционная) + EmployeeDocumentBlob/EmployeeGroups
#  (ex-Mongo → JSONB, решение D6) — порт services/hr/app/models/document.py +
#  services/hr/app/mongo.py (коллекции hr_documents, hr_employee_groups).
# ═══════════════════════════════════════════════════════════════════════════

class Document(HrBase):
    """Порт services/hr/app/models/document.py::Document.

    Таблица — дефолтное имя Django: hr_document (не hr_documents исходника,
    решение D2, как и у остальных моделей домена).

    Оба FK (``employee``/``uploaded_by``) — NOT NULL без явного ondelete в
    исходнике -> PROTECT (тот же выбор, что для Vacancy.department/position,
    Application.vacancy). Без ``db_index=False`` — исходник не индексирует их
    явно, но конвенция порта (см. Vacancy.department/position) не убирает
    дефолтную индексацию Django FK без документированной причины (составной
    индекс, левый префикс и т.п.) — здесь такой причины нет.

    ``metadata`` — исходник называет атрибут ``metadata_`` (маппится на
    колонку ``metadata``) ТОЛЬКО потому, что SQLAlchemy ``DeclarativeBase``
    резервирует имя ``metadata`` под свой ``MetaData``-реестр на уровне
    класса; Django такого ограничения не имеет, поэтому колонка и атрибут
    здесь называются одинаково — ``metadata``. Alias сохраняется на уровне
    wire-контракта в ``schemas.DocumentCreate`` (``metadata_``, alias
    ``"metadata"``), а не в модели.

    ``mime_type`` — клиентский SQLAlchemy ``default=...`` (не
    ``server_default``), но, как и у остальных подобных полей в этом файле
    (``Vacancy.description``, ``TimeEntry.break_minutes``, ...), порт всё
    равно ставит ``db_default``: вставка мимо ORM в NOT NULL-колонку иначе
    упадёт.
    """

    employee = models.ForeignKey(
        Employee, on_delete=models.PROTECT, related_name="documents",
    )
    title = models.CharField(max_length=255)
    doc_type = models.CharField(max_length=50)  # contract | order | certificate
    file_path = models.CharField(max_length=500)
    file_size = models.IntegerField()
    mime_type = models.CharField(
        max_length=100,
        default="application/octet-stream",
        db_default="application/octet-stream",
    )
    uploaded_by = models.ForeignKey(
        Employee, on_delete=models.PROTECT, related_name="uploaded_documents",
    )
    metadata = models.JSONField(null=True, blank=True)

    def __str__(self) -> str:
        return f"<Document(id={self.id}, title='{self.title}', employee_id={self.employee_id})>"


class EmployeeDocumentBlob(models.Model):
    """Ex-Mongo коллекция ``hr_documents`` → JSONB (решение D6, PLAN.md §6.3).

    Таблица — дефолтное имя Django: hr_employeedocumentblob. ``employee_id``/
    ``doc_type``/``created_at`` — промотированы в реальные колонки (порт
    ``mongo.ensure_indexes``: ``create_index("sql_employee_id")``,
    ``create_index("doc_type")``, составной
    ``create_index([("sql_employee_id", 1), ("doc_type", 1)])``,
    ``create_index("created_at")`` — 4 индекса исходника, все воспроизведены
    ниже). ``data`` — ВСЁ остальное тело mongo-документа (``title``,
    ``content``, ``file_url``, ``file_size_bytes``, ``mime_type``, ``tags``,
    ``metadata``, ``updated_at`` как isoformat-строка, ``created_by_user_id``)
    — целиком, без выделения под-полей в отдельные колонки, буквально как
    просит бриф ("data (JSONField, всё тело)").

    ``employee_id`` НЕ ``ForeignKey`` — в исходнике это ``sql_employee_id``,
    "синтетический" внешний ключ, поддерживаемый по конвенции, а не FK-
    constraint'ом БД (докстринг ``app/mongo.py``/``app/schemas/mongo_document.py``
    прямо это оговаривает: "The link is maintained by convention, not by a
    database constraint"). Буквальный порт сохраняет это — обычный
    ``IntegerField``, не ``ForeignKey``.
    """

    employee_id = models.IntegerField(db_index=True)
    doc_type = models.CharField(max_length=50, db_index=True)
    data = models.JSONField(default=dict, db_default={})
    created_at = models.DateTimeField(db_default=Now(), db_index=True)

    class Meta:
        indexes = [models.Index(fields=["employee_id", "doc_type"])]

    def __str__(self) -> str:
        return f"<EmployeeDocumentBlob(id={self.id}, employee_id={self.employee_id}, doc_type='{self.doc_type}')>"


class EmployeeGroups(models.Model):
    """Ex-Mongo коллекция ``hr_employee_groups`` → JSONB (решение D6).

    Таблица — дефолтное имя Django: hr_employeegroups. Порт
    ``EmployeeGroupsService``/Т-2 repeating groups (``education``,
    ``experience``, ``relatives``) — под-модуль ``employee_card``, ещё НЕ
    перенесённый в apps.hr (см. ``services/hr/app/api/v1/employee_card.py``);
    здесь появляется только модель данных (бриф, решение D6, п.3) — CRUD и
    роутинг T-2 groups остаются задачей под-модуля employee_card.

    Ни ``created_at``, ни ``updated_at`` — в исходном mongo-документе их нет
    (``EmployeeGroupsService.read/replace`` не пишет никаких таймстампов),
    поэтому ``HrBase`` не наследуется буквально: только 2 поля, как в брифе.

    CRUD и роутинг Т-2 groups (``GET``/``PUT /employees/{id}/card/groups``) —
    под-модуль ``employee_card`` (см. секцию ниже) — перенесены.
    """

    employee_id = models.IntegerField(unique=True)
    data = models.JSONField(default=dict, db_default={})

    def __str__(self) -> str:
        return f"<EmployeeGroups(employee_id={self.employee_id})>"


# ═══════════════════════════════════════════════════════════════════════════
#  employee_card: EmployeeCard — Т-2 скалярные поля (финансы/личные данные/
#  сертификаты) — порт services/hr/app/models/employee_card.py.
# ═══════════════════════════════════════════════════════════════════════════

class EmployeeCard(HrBase):
    """Порт services/hr/app/models/employee_card.py::EmployeeCard.

    Таблица — дефолтное имя Django: hr_employeecard (не hr_employee_card
    исходника, решение D2, как и у остальных моделей домена). Наследует
    ``HrBase`` — исходник наследует ``BaseModel`` (created_at/updated_at),
    как Employee/Department/Position, НЕ голый ``models.Model``, как
    EmployeeGroups/EmployeeDocumentBlob выше (у тех в исходном mongo-
    документе таймстампов нет вовсе — здесь же обычная SQL-таблица 1:1 с
    server_default на обеих колонках).

    ``employee_id`` — ``unique=True`` у исходника (``mapped_column(...,
    unique=True, index=True)`` — карточка ровно одна на сотрудника) ->
    ``OneToOneField`` (тот же приём, что EmployeeWeekTemplate/
    EmployeeShiftAssignment выше: Django W342 рекомендует OneToOneField
    вместо ``ForeignKey(unique=True)``). ``db_index=False``: unique уже даёт
    свой уникальный индекс — отдельный btree был бы чистым дублем (исходник
    тоже несёт ровно один индекс на этой колонке — комбинированный
    unique+index, не два отдельных).

    Остальные поля — скалярные Т-2 секции (без дефолтов в исходнике, все
    nullable): financial (salary/bonus/bank_account), personal
    (passport_data/inn/birth_date/birth_place/citizenship), certs
    (sro_permit_number/sro_permit_expiry/safety_cert_number/
    safety_cert_expiry). Полевой RBAC-гейтинг этих секций живёт в
    ``services/employee_card_t2_service.py``, не в модели.
    """

    employee = models.OneToOneField(
        Employee, on_delete=models.CASCADE, related_name="card", db_index=False,
    )
    salary = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    bonus = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    bank_account = models.CharField(max_length=64, null=True, blank=True)
    passport_data = models.TextField(null=True, blank=True)
    inn = models.CharField(max_length=20, null=True, blank=True)
    birth_date = models.DateField(null=True, blank=True)
    birth_place = models.CharField(max_length=255, null=True, blank=True)
    citizenship = models.CharField(max_length=100, null=True, blank=True)
    sro_permit_number = models.CharField(max_length=100, null=True, blank=True)
    sro_permit_expiry = models.DateField(null=True, blank=True)
    safety_cert_number = models.CharField(max_length=100, null=True, blank=True)
    safety_cert_expiry = models.DateField(null=True, blank=True)

    def __str__(self) -> str:
        return f"<EmployeeCard(employee_id={self.employee_id})>"


# ═══════════════════════════════════════════════════════════════════════════
#  time-core: TimeEntry + StaffingPosition + PersonnelHistory — порт
#  services/hr/app/models/{time_tracking,staffing,personnel_history}.py
# ═══════════════════════════════════════════════════════════════════════════

class TimeEntry(HrBase):
    """Запись учёта рабочего времени — порт models/time_tracking.py.

    Таблица — дефолтное имя Django: hr_timeentry (не hr_time_entries
    исходника, решение D2, как и у остальных моделей домена).
    """

    # FK NOT NULL без явного ondelete в исходнике -> PROTECT (та же практика,
    # что для Employee.department/position, Vacancy.department/position).
    # db_index=False: составной UniqueConstraint (employee, date, start_time)
    # ниже уже покрывает employee_id своим левым префиксом — исходник тоже не
    # индексирует employee_id отдельно (нет отдельного index=True на колонке,
    # только UniqueConstraint) — тот же приём, что и у
    # PositionWeightAudit.position (левый префикс составного индекса).
    employee = models.ForeignKey(
        Employee, on_delete=models.PROTECT, related_name="time_entries", db_index=False,
    )
    date = models.DateField()
    start_time = models.TimeField()
    end_time = models.TimeField()
    break_minutes = models.IntegerField(default=0, db_default=0)
    description = models.TextField(null=True, blank=True)
    project = models.CharField(max_length=255, null=True, blank=True)
    task = models.CharField(max_length=255, null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["employee", "date", "start_time"], name="uq_employee_time_entry",
            ),
        ]

    def __str__(self) -> str:
        return f"<TimeEntry(id={self.id}, employee_id={self.employee_id}, date={self.date})>"


class StaffingPosition(HrBase):
    """Строка штатного расписания — порт models/staffing.py.

    Таблица — дефолтное имя Django: hr_staffingposition (не
    hr_staffing_positions исходника, решение D2). Оба FK исходник объявляет
    с явным ``index=True`` — дефолтное индексирование Django FK уже
    воспроизводит это без дополнительных пометок.
    """

    position = models.ForeignKey(
        Position, on_delete=models.CASCADE, related_name="staffing_lines",
    )
    department = models.ForeignKey(
        Department, on_delete=models.CASCADE, related_name="staffing_lines",
    )
    grade = models.IntegerField(null=True, blank=True)
    headcount = models.DecimalField(max_digits=5, decimal_places=2, default=1, db_default=1)
    salary = models.DecimalField(max_digits=12, decimal_places=2, default=0, db_default=0)
    note = models.CharField(max_length=255, null=True, blank=True)

    def __str__(self) -> str:
        return (f"<StaffingPosition(id={self.id}, position_id={self.position_id}, "
                f"department_id={self.department_id})>")


class PersonnelHistoryEventType(models.TextChoices):
    """Порт ``EVENT_TYPES`` (простой tuple в исходнике, models/personnel_history.py)."""

    HIRED = "hired", "Принят"
    DISMISSED = "dismissed", "Уволен"
    TRANSFER = "transfer", "Перевод"
    PROMOTION = "promotion", "Повышение"
    DEMOTION = "demotion", "Понижение"
    OTHER = "other", "Другое"


class PersonnelHistory(HrBase):
    """Кадровая история (HR-событие) — порт models/personnel_history.py.

    Таблица — дефолтное имя Django: hr_personnelhistory (не
    hr_personnel_history исходника, решение D2).
    """

    employee = models.ForeignKey(
        Employee, on_delete=models.CASCADE, related_name="personnel_history",
    )
    event_type = models.CharField(
        max_length=20,
        choices=PersonnelHistoryEventType.choices,
        default=PersonnelHistoryEventType.OTHER,
        db_default=PersonnelHistoryEventType.OTHER.value,
        db_index=True,
    )
    event_date = models.DateField(db_index=True)

    from_department = models.ForeignKey(
        Department, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="personnel_history_from",
    )
    to_department = models.ForeignKey(
        Department, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="personnel_history_to",
    )
    from_position = models.ForeignKey(
        Position, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="personnel_history_from_position",
    )
    to_position = models.ForeignKey(
        Position, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="personnel_history_to_position",
    )

    order_number = models.CharField(max_length=64, default="", db_default="")
    comment = models.TextField(default="", db_default="")

    # D10-подобное решение (см. AuditLog.changed_by выше): TokenPayload.user_id
    # платформенного пользователя (то же ID-пространство, что Employee.user_id,
    # решение D7) — НЕ PK hr_employees, поэтому простой IntegerField без FK,
    # ровно как и в исходнике (комментарий там: "no FK — user lives in
    # user-service").
    created_by = models.IntegerField(null=True, blank=True, db_index=True)

    def __str__(self) -> str:
        return f"<PersonnelHistory(id={self.id}, employee_id={self.employee_id}, event={self.event_type})>"


# ═══════════════════════════════════════════════════════════════════════════
#  calendar: WeekTemplate + CalendarDay + EmployeeWeekTemplate + ShiftPattern +
#  EmployeeShiftAssignment + EmployeeDayOverride — порт services/hr/app/models/
#  calendar.py (6 таблиц).
# ═══════════════════════════════════════════════════════════════════════════
#
# day_type у исходника — ПРОСТАЯ String(16)/String(20), без SQLAlchemy Enum на
# уровне колонки (валидация набора {"working","weekend","holiday","short"}
# живёт только в pydantic-схемах роутера — app/schemas/calendar.py). Порт
# сохраняет это буквально: CharField БЕЗ choices= (никакой TextChoices здесь
# не было бы у самого исходника — choices были бы ложной строгостью на уровне
# БД, которой контракт не несёт).
#
# default=... у исходника (WeekTemplate.days/is_default, ShiftPattern.slots/
# holidays_off, CalendarDay/EmployeeDayOverride.norm_hours) — КЛИЕНТСКИЙ
# SQLAlchemy default (не server_default), но, как и у TimeEntry.break_minutes
# выше, порт всё равно ставит db_default: тот же принцип HrBase — без него
# вставка мимо ORM в NOT NULL колонку падает.

class WeekTemplate(HrBase):
    """Недельный шаблон (5/2, 6/1, ...) — порт models/calendar.py::WeekTemplate.

    Таблица — дефолтное имя Django: hr_weektemplate (не hr_week_templates
    исходника, решение D2).
    """

    name = models.CharField(max_length=100)
    is_default = models.BooleanField(default=False, db_default=False)
    # {"0": {"type": "working"|"weekend", "hours": <number>}, ..., "6": {...}}
    # — ключи "0".."6" (понедельник..воскресенье), валидируется в schemas.py.
    days = models.JSONField(default=dict, db_default={})

    def __str__(self) -> str:
        return self.name


class CalendarDay(HrBase):
    """Национальный оверрайд дня (праздник/перенос) — порт
    models/calendar.py::CalendarDay.

    Таблица — дефолтное имя Django: hr_calendarday (не hr_calendar_days
    исходника, решение D2). ``day`` — ``unique=True`` у исходника даёт И
    ``unique``, И ``index`` НА ОДНОЙ колонке (SQLAlchemy
    ``unique=True, index=True`` на одной колонке сливаются в один уникальный
    индекс, не два) — Django ``unique=True`` уже создаёт ровно такой же
    единственный уникальный индекс сам по себе, доп. ``db_index`` не нужен.
    """

    day = models.DateField(unique=True)
    day_type = models.CharField(max_length=16)
    norm_hours = models.DecimalField(max_digits=4, decimal_places=2, default=0, db_default=0)
    note = models.CharField(max_length=255, null=True, blank=True)

    def __str__(self) -> str:
        return f"{self.day} ({self.day_type})"


class EmployeeWeekTemplate(HrBase):
    """Назначение недельного шаблона сотруднику (не более одного) — порт
    models/calendar.py::EmployeeWeekTemplate.

    Таблица — дефолтное имя Django: hr_employeeweektemplate (не
    hr_employee_week_template исходника, решение D2). ``employee_id`` —
    ``unique=True`` у исходника (максимум одна строка на сотрудника) ->
    ``OneToOneField`` (Django-предупреждение W342 явно рекомендует его вместо
    ``ForeignKey(unique=True)``). ``db_index=False``: unique-ограничение уже
    даёт свой уникальный индекс — отдельный btree-индекс поверх него был бы
    чистым дублем (исходник тоже несёт РОВНО один индекс на этой колонке —
    комбинированный unique+index).
    """

    employee = models.OneToOneField(
        Employee, on_delete=models.CASCADE, related_name="week_template_assignment", db_index=False,
    )
    week_template = models.ForeignKey(
        WeekTemplate, on_delete=models.CASCADE, related_name="employee_assignments",
    )

    def __str__(self) -> str:
        return f"<EmployeeWeekTemplate(employee_id={self.employee_id}, week_template_id={self.week_template_id})>"


class ShiftPattern(HrBase):
    """Циклический график смен — порт models/calendar.py::ShiftPattern.

    Таблица — дефолтное имя Django: hr_shiftpattern (не hr_shift_patterns
    исходника, решение D2).
    """

    name = models.CharField(max_length=100)
    # [{"type": "work"|"off", "hours": <number>}, ...]; len(slots) = длина цикла.
    slots = models.JSONField(default=list, db_default=[])
    holidays_off = models.BooleanField(default=False, db_default=False)

    def __str__(self) -> str:
        return self.name


class EmployeeShiftAssignment(HrBase):
    """Назначение сменного графика сотруднику (не более одного;
    взаимоисключающе с EmployeeWeekTemplate на уровне сервиса) — порт
    models/calendar.py::EmployeeShiftAssignment.

    Таблица — дефолтное имя Django: hr_employeeshiftassignment (не
    hr_employee_shift_assignment исходника, решение D2). Тот же приём, что и
    EmployeeWeekTemplate.employee выше: OneToOneField + db_index=False (unique
    уже покрывает индекс, исходник несёт ровно один индекс на колонке).
    """

    employee = models.OneToOneField(
        Employee, on_delete=models.CASCADE, related_name="shift_assignment", db_index=False,
    )
    shift_pattern = models.ForeignKey(
        ShiftPattern, on_delete=models.CASCADE, related_name="employee_assignments",
    )
    anchor_date = models.DateField()

    def __str__(self) -> str:
        return f"<EmployeeShiftAssignment(employee_id={self.employee_id}, shift_pattern_id={self.shift_pattern_id})>"


class EmployeeDayOverride(HrBase):
    """Персональный оверрайд дня сотрудника — порт
    models/calendar.py::EmployeeDayOverride.

    Таблица — дефолтное имя Django: hr_employeedayoverride (не
    hr_employee_day_override исходника, решение D2). В ОТЛИЧИЕ от
    EmployeeWeekTemplate/EmployeeShiftAssignment выше: здесь исходник несёт
    ДВА независимых индекса на ``employee_id`` — явный ``index=True`` НА
    КОЛОНКЕ (одиночный) ПЛЮС составной ``UniqueConstraint(employee_id, day)``
    (у которого employee_id — только левый префикс). Это не совпадает со
    случаем PositionWeightAudit.position (там был ровно один составной индекс
    без отдельного одиночного) — тут db_index НЕ убираем: FK
    ``employee`` оставлен с дефолтным Django db_index=True, что и
    воспроизводит оба индекса исходника (одиночный от FK + составной от
    UniqueConstraint ниже).
    """

    employee = models.ForeignKey(
        Employee, on_delete=models.CASCADE, related_name="day_overrides",
    )
    day = models.DateField()
    day_type = models.CharField(max_length=16)
    norm_hours = models.DecimalField(max_digits=4, decimal_places=2, default=0, db_default=0)
    note = models.CharField(max_length=255, null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["employee", "day"], name="uq_hr_emp_day_override"),
        ]

    def __str__(self) -> str:
        return f"<EmployeeDayOverride(employee_id={self.employee_id}, day={self.day})>"


# ═══════════════════════════════════════════════════════════════════════════
#  pmo: PMO + PMODepartment + PMOPosition + PMOMember — порт
#  services/hr/app/models/pmo.py (4 таблицы).
# ═══════════════════════════════════════════════════════════════════════════
#
# Таблицы — дефолтные имена Django (решение D2, как и весь остальной файл):
# hr_pmo (не hr_pmos исходника), hr_pmodepartment (не hr_pmo_departments),
# hr_pmoposition (не hr_pmo_positions), hr_pmomember (не hr_pmo_members).
#
# PMODepartment/PMOPosition — составной PK (``pmo_id``, ``department_id``/
# ``position_id``) в исходнике (оба поля ``primary_key=True`` у SQLAlchemy,
# без отдельного суррогатного id) -> Django 5.2 ``models.CompositePrimaryKey``
# (поле обязано называться ``pk``). PMOMember, в отличие от них, наследует
# ``BaseModel``... нет — НЕ наследует: исходник объявляет её как ``Base``
# (не ``BaseModel``) с собственным явным ``id: Mapped[int] = mapped_column(
# Integer, primary_key=True, autoincrement=True)`` — обычный суррогатный PK,
# как у остальных моделей порта без HrBase (см. OrgSettings). Ни у неё, ни у
# PMODepartment/PMOPosition НЕТ created_at/updated_at (только PMO наследует
# BaseModel в исходнике -> здесь HrBase).


class PMOStatus(models.TextChoices):
    ACTIVE = "active", "Активен"
    SUSPENDED = "suspended", "Приостановлен"
    CLOSED = "closed", "Закрыт"


class PMO(HrBase):
    """Проектный офис — порт models/pmo.py::PMO."""

    name = models.CharField(max_length=200)
    code = models.CharField(max_length=50, unique=True)
    description = models.TextField(null=True, blank=True)
    # Nullable FK без явного ondelete в исходнике -> SET_NULL (тот же выбор,
    # что для Department.manager/Vacancy.assigned_recruiter выше в этом файле).
    head_employee = models.ForeignKey(
        Employee, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="headed_pmos",
    )
    status = models.CharField(
        max_length=20,
        choices=PMOStatus.choices,
        default=PMOStatus.ACTIVE,
        db_default=PMOStatus.ACTIVE.value,
    )

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(status__in=list(PMOStatus.values)),
                name="ck_pmo_status",
            ),
        ]
        # СТРАННОСТЬ исходника, НЕ воспроизводим байт-в-байт: колонка ``code``
        # несёт И column-level ``unique=True`` (mapped_column), И ОТДЕЛЬНЫЙ
        # именованный ``Index("ix_hr_pmos_code", "code", unique=True)`` в
        # __table_args__ — это два независимых SQLAlchemy-конструкта на
        # одной колонке (в отличие от CalendarDay.day выше, где unique=True
        # И index=True стоят на ОДНОМ вызове mapped_column и сливаются в один
        # индекс сами), то есть реально ДВА идентичных уникальных индекса на
        # ``code`` в БД исходника. Как и в остальных задокументированных
        # местах этого файла (PositionWeightAudit.position,
        # EmployeeWeekTemplate/EmployeeShiftAssignment.employee) — не плодим
        # дубль, оставляем один уникальный индекс (field-level unique=True
        # выше). ``status`` — обычный некомпозитный индекс исходника
        # (Index("ix_hr_pmos_status", "status")) -> db_index=True на поле.
        indexes = [models.Index(fields=["status"], name="ix_hr_pmos_status")]

    def __str__(self) -> str:
        return f"<PMO(id={self.id}, code='{self.code}', status='{self.status}')>"


class PMODepartmentRole(models.TextChoices):
    OWNER = "owner", "Владелец"
    STAKEHOLDER = "stakeholder", "Стейкхолдер"
    SUPPORT = "support", "Поддержка"


class PMODepartment(models.Model):
    """Связь PMO-отдел — порт models/pmo.py::PMODepartment.

    Составной PK (``pmo``, ``department``) — оба поля были ``primary_key=True``
    у исходника, без суррогатного id (Django 5.2 ``CompositePrimaryKey``).
    ``pmo`` — ``db_index=False``: составной PK уже покрывает эту колонку
    ЛЕВЫМ префиксом (тот же приём, что PositionWeightAudit.position выше),
    отдельный btree-индекс поверх был бы чистым дублем. ``department`` —
    НЕ левый префикс композитного PK -> обычный авто-индекс Django FK
    оставлен (правило брифа: db_index=False только когда составной
    индекс/unique покрывает колонку левым префиксом, иначе — авто-индекс).
    """

    pmo = models.ForeignKey(PMO, on_delete=models.CASCADE, related_name="pmo_departments", db_index=False)
    department = models.ForeignKey(Department, on_delete=models.CASCADE, related_name="pmo_departments")
    role = models.CharField(
        max_length=20,
        choices=PMODepartmentRole.choices,
        default=PMODepartmentRole.OWNER,
        db_default=PMODepartmentRole.OWNER.value,
    )

    pk = models.CompositePrimaryKey("pmo", "department")

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(role__in=list(PMODepartmentRole.values)),
                name="ck_pmo_dept_role",
            ),
        ]

    def __str__(self) -> str:
        return f"<PMODepartment(pmo_id={self.pmo_id}, department_id={self.department_id})>"


class PMOPosition(models.Model):
    """Требуемая/рекомендуемая должность PMO — порт models/pmo.py::PMOPosition.

    Составной PK (``pmo``, ``position``) — та же схема, что и PMODepartment
    выше. ``pmo`` — ``db_index=False`` (левый префикс композитного PK);
    ``position`` — обычный авто-индекс Django FK (не покрыт левым префиксом).
    Никаких CheckConstraint/явных индексов в исходнике сверх составного PK.
    """

    pmo = models.ForeignKey(PMO, on_delete=models.CASCADE, related_name="pmo_positions", db_index=False)
    position = models.ForeignKey(Position, on_delete=models.CASCADE, related_name="pmo_positions")
    is_required = models.BooleanField(default=False, db_default=False)
    headcount = models.IntegerField(default=1, db_default=1)

    pk = models.CompositePrimaryKey("pmo", "position")

    def __str__(self) -> str:
        return f"<PMOPosition(pmo_id={self.pmo_id}, position_id={self.position_id})>"


class PMOMembershipType(models.TextChoices):
    PERMANENT = "permanent", "Постоянное"
    ASSIGNED = "assigned", "Назначенное"
    CONSULTING = "consulting", "Консультационное"


class PMOMember(models.Model):
    """Членство сотрудника в PMO — порт models/pmo.py::PMOMember.

    НЕ наследует HrBase (исходник — ``Base``, не ``BaseModel``): ни
    created_at, ни updated_at. Суррогатный ``id`` — обычный дефолтный
    AutoField Django (исходник тоже несёт явный autoincrement integer PK,
    просто без HrBase). ``pmo``/``employee`` — обычные (не составные) FK,
    оставлены с дефолтным авто-индексом Django: исходник несёт РОВНО те же
    два одиночных индекса явно (``Index("ix_hr_pmo_members_pmo", "pmo_id")``,
    ``Index("ix_hr_pmo_members_employee", "employee_id")``) — авто-индекс FK
    воспроизводит их без доп. пометок (та же логика, что Position.department/
    Employee.department/position и весь остальной файл).

    Частичные уникальные индексы (``postgresql_where=...`` исходника) —
    ``UniqueConstraint(condition=Q(...))``:
      * ``ux_hr_pmo_members_open_employee`` — не более ОДНОГО открытого
        (``to_date IS NULL``) членства сотрудника в одном PMO;
      * ``ux_hr_pmo_members_open_primary`` — не более ОДНОГО открытого
        первичного (``is_primary AND to_date IS NULL``) членства на PMO.
    """

    pmo = models.ForeignKey(PMO, on_delete=models.CASCADE, related_name="members")
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="pmo_memberships")
    membership_type = models.CharField(
        max_length=20,
        choices=PMOMembershipType.choices,
        default=PMOMembershipType.PERMANENT,
        db_default=PMOMembershipType.PERMANENT.value,
    )
    position_in_pmo = models.CharField(max_length=200, null=True, blank=True)
    from_date = models.DateField()
    to_date = models.DateField(null=True, blank=True)
    allocation_percent = models.SmallIntegerField(default=100, db_default=100)
    is_primary = models.BooleanField(default=False, db_default=False)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(membership_type__in=list(PMOMembershipType.values)),
                name="ck_pmo_member_type",
            ),
            models.CheckConstraint(
                condition=models.Q(allocation_percent__gte=0) & models.Q(allocation_percent__lte=100),
                name="ck_pmo_member_allocation_pct",
            ),
            models.CheckConstraint(
                condition=models.Q(to_date__isnull=True) | models.Q(to_date__gte=models.F("from_date")),
                name="ck_pmo_member_dates",
            ),
            models.UniqueConstraint(
                fields=["pmo", "employee"],
                condition=models.Q(to_date__isnull=True),
                name="ux_hr_pmo_members_open_employee",
            ),
            models.UniqueConstraint(
                fields=["pmo"],
                condition=models.Q(is_primary=True, to_date__isnull=True),
                name="ux_hr_pmo_members_open_primary",
            ),
        ]

    def __str__(self) -> str:
        return (f"<PMOMember(id={self.id}, pmo_id={self.pmo_id}, "
                f"employee_id={self.employee_id})>")
