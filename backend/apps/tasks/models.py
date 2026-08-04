"""Task domain models — idiomatic Django, built from scratch in ``public``.

Ported from the ``services/task`` FastAPI microservice (SQLAlchemy +
alembic). Per PLAN.md §3 this repo is a standalone copy that never runs
side-by-side with the FastAPI stack, so alembic parity is explicitly NOT a
goal: table/constraint/index names are Django-generated, PG enums become
``TextChoices``, and the schema is built by a natural ``makemigrations``.

Two tables from the original are deliberately **absent** (decision Р2,
PLAN.md §6.1): ``task_users`` and ``task_departments`` were denormalised
replicas kept in sync over Redis pub/sub from user-service and hr-service.
In the Django monolith there is nothing to replicate — apps talk through
``interface.py``. Every column that was a FK into one of those two replica
tables is therefore a plain, FK-less integer id here:

* ``reporter_id`` / ``assignee_id`` / ``supervisor_id`` / ``owner_id`` /
  ``actor_id`` / ``recipient_id`` / ``user_id`` / ``employee_id``
  — resolved through ``apps.users.interface.get_users_brief``;
* ``department_id`` — resolved through ``apps.hr.interface``.

Consequences worth knowing, because the original leaned on those FKs:

* ``ON DELETE CASCADE`` from the replica tables is gone. Nothing cascades
  from a deleted user; rows keep the orphaned id and display-name hydration
  simply yields ``None`` for it — the same result the original produced when
  the replica lagged, so the API shape is unchanged.
* The denormalised ``*_name`` / ``avatar_url`` attributes the SQLAlchemy
  models exposed as ``@property`` off a loaded relationship do not exist on
  these models. They are response-shape concerns and are computed in the
  service layer, which batches the ``interface`` lookups — a model-level
  property would have meant an N+1 across an app boundary.

``db_default=`` is set on every column carrying a concrete scalar default so
a direct INSERT that bypasses the ORM still lands sane values, and
``db_index=True`` mirrors every ``index=True`` in the SQLAlchemy source (FK
columns are indexed by Django automatically and get no redundant flag) —
PLAN.md §3's "не терять индексы" rule.
"""

from django.db import models
from django.db.models.functions import Now
from django.utils import timezone


# ─────────────────────────────────────────────────────────────────────────
# Enumerations (PG ENUM in the original → TextChoices here)
# ─────────────────────────────────────────────────────────────────────────

class Status(models.TextChoices):
    BACKLOG = "backlog"
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    IN_REVIEW = "in_review"
    BLOCKED = "blocked"
    DONE = "done"
    CANCELLED = "cancelled"


class Priority(models.TextChoices):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    TRIVIAL = "trivial"


class ProjectStatus(models.TextChoices):
    ACTIVE = "active"
    COMPLETED = "completed"
    ARCHIVED = "archived"


class LinkType(models.TextChoices):
    BLOCKS = "blocks"
    IS_BLOCKED_BY = "is_blocked_by"
    RELATES_TO = "relates_to"
    DUPLICATES = "duplicates"


class AssigneeRole(models.TextChoices):
    PRIMARY = "primary"
    COLLABORATOR = "collaborator"


# Terminal statuses — entering one stamps ``completed_at``.
TERMINAL_STATUSES = frozenset({Status.DONE, Status.CANCELLED})

# FSM transitions: from_state -> allowed target states. Copied verbatim from
# services/task/app/models/task.py. Deliberately permissive: workflow tasks
# routinely bounce between states (unblock then re-cancel) and a strict graph
# causes user friction.
TRANSITIONS: dict[str, frozenset[str]] = {
    Status.BACKLOG: frozenset({Status.TODO, Status.IN_PROGRESS, Status.CANCELLED}),
    Status.TODO: frozenset({Status.IN_PROGRESS, Status.BLOCKED, Status.BACKLOG,
                            Status.CANCELLED}),
    Status.IN_PROGRESS: frozenset({Status.IN_REVIEW, Status.BLOCKED, Status.DONE,
                                   Status.TODO, Status.CANCELLED}),
    Status.IN_REVIEW: frozenset({Status.DONE, Status.IN_PROGRESS, Status.BLOCKED,
                                 Status.CANCELLED}),
    Status.BLOCKED: frozenset({Status.IN_PROGRESS, Status.TODO, Status.CANCELLED}),
    Status.DONE: frozenset({Status.IN_PROGRESS, Status.CANCELLED}),   # reopen
    Status.CANCELLED: frozenset({Status.BACKLOG, Status.TODO}),       # restore
}


# ─────────────────────────────────────────────────────────────────────────
# Reference data
# ─────────────────────────────────────────────────────────────────────────

class TaskType(models.Model):
    """A user-configurable task type — DB-backed replacement for the legacy
    PG enum (``task``/``bug``/``story``/``epic``/``subtask``).

    Different business domains have wildly different vocabularies for "what
    kind of work is this": dev teams talk about bug/story/epic, ops wants
    maintenance/incident, HR wants onboarding/offboarding. The five original
    enum values are seeded as ``is_system`` rows and are protected from
    deletion through the API so historical data keeps resolving.
    """

    slug = models.CharField(max_length=50, unique=True)
    name = models.CharField(max_length=100)
    color = models.CharField(max_length=20, default="#6b7280", db_default="#6b7280")
    icon = models.CharField(max_length=50, null=True, blank=True)
    is_system = models.BooleanField(default=False, db_default=False)

    created_at = models.DateTimeField(auto_now_add=True, db_default=Now())
    updated_at = models.DateTimeField(auto_now=True, db_default=Now())

    class Meta:
        verbose_name = "Тип задачи"
        verbose_name_plural = "Типы задач"

    def __repr__(self) -> str:  # pragma: no cover
        return f"<TaskType id={self.id} slug={self.slug!r}>"


class Label(models.Model):
    """Label/tag for task categorisation."""

    name = models.CharField(max_length=100, unique=True)
    color = models.CharField(max_length=7, default="#808080", db_default="#808080")

    created_at = models.DateTimeField(auto_now_add=True, db_default=Now())
    updated_at = models.DateTimeField(auto_now=True, db_default=Now())

    class Meta:
        verbose_name = "Метка"
        verbose_name_plural = "Метки"

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Label id={self.id} name={self.name!r}>"


class EquipmentCategory(models.Model):
    """Тип техники: «кара (вилопогрузчик)», «кран», «самосвал».

    Раньше это был свободный текст в ``Equipment.category``, и пока техника
    только числилась в парке, текста хватало. Планирование потребности его
    ломает: «нужно 2 кары» — это ссылка на ТИП, а не на две конкретные
    машины, и по свободному тексту такую ссылку не построить («кара»,
    «Кара», «кара (вилопогрузчик)» — три разных типа для БД и один для
    человека). ``ResourceRequirement.equipment_category`` ниже — и есть тот
    второй потребитель, ради которого справочник стал таблицей.

    Живёт в ``tasks``, а не в отдельной аппке, по причине из докстринга
    ``Site``: оба потребителя (``Equipment`` и ``ResourceRequirement``)
    здесь же, значит настоящий FK достаётся бесплатно.
    """

    slug = models.CharField(max_length=50, unique=True)
    name = models.CharField(max_length=100, unique=True)
    is_active = models.BooleanField(default=True, db_default=True, db_index=True)

    created_at = models.DateTimeField(auto_now_add=True, db_default=Now())
    updated_at = models.DateTimeField(auto_now=True, db_default=Now())

    class Meta:
        verbose_name = "Категория техники"
        verbose_name_plural = "Категории техники"

    def __repr__(self) -> str:  # pragma: no cover
        return f"<EquipmentCategory id={self.id} slug={self.slug!r}>"


class WorkRole(models.Model):
    """Роль человека в потребности: «монтажник», «стропальщик», «водитель».

    Намеренно НЕ ``hr.Position``. Во-первых, ``hr.interface`` должность
    справочником не отдаёт — только строкой ``position_title`` внутри брифа
    сотрудника, так что FK туда и не построить, не расширяя чужой контракт.
    Во-вторых, это осознанное решение аппки, а не обход ограничения:
    ``ContractorWorker.position_title`` уже развязан с ``hr.Position`` по той
    же причине — планируемая роль на объекте («нужен стропальщик») и штатная
    должность в кадрах живут своей жизнью и совпадают не всегда.
    """

    slug = models.CharField(max_length=50, unique=True)
    name = models.CharField(max_length=100, unique=True)
    is_active = models.BooleanField(default=True, db_default=True, db_index=True)

    created_at = models.DateTimeField(auto_now_add=True, db_default=Now())
    updated_at = models.DateTimeField(auto_now=True, db_default=Now())

    class Meta:
        verbose_name = "Рабочая роль"
        verbose_name_plural = "Рабочие роли"

    def __repr__(self) -> str:  # pragma: no cover
        return f"<WorkRole id={self.id} slug={self.slug!r}>"


class WorkVolumeUnit(models.TextChoices):
    PIECE = "piece", "шт"
    METER = "meter", "м"
    SQ_METER = "sq_meter", "м²"
    TON = "ton", "т"


class WorkVolumeType(models.Model):
    """Вид объёма работ: «валы», «трекерные конструкции», «панели».

    Единица измерения принадлежит ТИПУ, а не строке объёма: валы считают
    штуками всегда и везде. Держи её на ``SiteBlockVolume``/``TaskVolume`` —
    и один и тот же вид работ на соседних блоках можно было бы завести в
    штуках и в тоннах, после чего суммировать их стало бы нельзя, а именно
    суммирование и есть смысл этих таблиц.
    """

    slug = models.CharField(max_length=50, unique=True)
    name = models.CharField(max_length=100, unique=True)
    unit = models.CharField(
        max_length=20, choices=WorkVolumeUnit.choices,
        default=WorkVolumeUnit.PIECE, db_default=WorkVolumeUnit.PIECE,
    )
    is_active = models.BooleanField(default=True, db_default=True, db_index=True)

    created_at = models.DateTimeField(auto_now_add=True, db_default=Now())
    updated_at = models.DateTimeField(auto_now=True, db_default=Now())

    class Meta:
        verbose_name = "Вид объёма работ"
        verbose_name_plural = "Виды объёмов работ"

    def __repr__(self) -> str:  # pragma: no cover
        return f"<WorkVolumeType id={self.id} slug={self.slug!r}>"


class EquipmentOwnership(models.TextChoices):
    OWN = "own", "Собственная"
    CONTRACTOR = "contractor", "Подрядчика"
    RENTED = "rented", "Аренда"


class Equipment(models.Model):
    """Physical resource (machinery/vehicle) the task domain owns outright.

    Unlike the former user/department replicas this is a first-class entity —
    there is no equipment service to replicate from. Used by the resource
    Gantt to group tasks by machine.

    ``ownership`` — три значения, а не «NULL в ``contractor`` значит наша»:
    иначе «своя» и «не заполнено» неразличимы, и парк, который вёлся до
    появления подрядчиков, пришлось бы считать неизвестным. С явным
    значением существующие строки честно становятся ``own``.
    """

    name = models.CharField(max_length=200)
    inventory_no = models.CharField(max_length=50, null=True, blank=True)
    # Был свободный текст — стал FK (см. докстринг EquipmentCategory).
    # ``PROTECT``: тип, на который ссылается парк, удалить нельзя — иначе
    # техника молча теряет классификацию, а потребности «2 кары» остаются
    # ссылаться в пустоту. Nullable, потому что у части исторических строк
    # категория не заполнена, и выдумывать её при бэкфилле не из чего.
    category = models.ForeignKey(
        EquipmentCategory, on_delete=models.PROTECT, null=True, blank=True,
        related_name="equipment",
    )
    is_active = models.BooleanField(default=True, db_default=True, db_index=True)

    ownership = models.CharField(
        max_length=20, choices=EquipmentOwnership.choices,
        default=EquipmentOwnership.OWN, db_default=EquipmentOwnership.OWN,
        db_index=True,
    )
    contractor = models.ForeignKey(
        "Contractor", on_delete=models.PROTECT, null=True, blank=True,
        related_name="equipment",
    )

    created_at = models.DateTimeField(auto_now_add=True, db_default=Now())
    updated_at = models.DateTimeField(auto_now=True, db_default=Now())

    class Meta:
        verbose_name = "Техника"
        verbose_name_plural = "Техника"
        constraints = [
            # Техника подрядчика обязана называть подрядчика. Стиль тот же,
            # что у ck_assignment_exactly_one_resource ниже: правило про одну
            # строку одной таблицы — значит место ему в БД, а не в сервисе.
            models.CheckConstraint(
                condition=~models.Q(ownership=EquipmentOwnership.CONTRACTOR)
                | models.Q(contractor__isnull=False),
                name="ck_equipment_contractor_owner",
            ),
        ]

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Equipment id={self.id} name={self.name!r}>"


class ContractorStatus(models.TextChoices):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    BLACKLISTED = "blacklisted"
    ARCHIVED = "archived"


class ContractorLevel(models.TextChoices):
    """Уровень допуска представителя подрядчика.

    Значения совпадают с тремя младшими членами
    ``htqweb.authn.levels.DepartmentLevel``, чтобы этап «вход для
    подрядчиков» переиспользовал готовые ``rank``/``meets`` без конвертации.
    Уровень — свойство ЧЕЛОВЕКА, а не организации: у одного подрядчика
    прораб и разнорабочий получают разные права.

    Согласованная матрица (заработает вместе с учётками):
      junior — только смотреть свои задачи;
      middle — плюс менять статус и процент, писать комментарии, грузить файлы;
      senior — плюс видеть все задачи своей организации по её объектам.
    """

    JUNIOR = "junior"
    MIDDLE = "middle"
    SENIOR = "senior"


class Contractor(models.Model):
    """Подрядная организация.

    Справочник. Учётных записей у организации нет и не будет — вход, когда
    он появится, будет у человека (``ContractorWorker.user_id``).

    Живёт в ``apps.tasks``, а не отдельным аппом, по той же причине, что и
    ``Site``: оба потребителя (``Task``, ``Equipment``) здесь же. Граница
    аппа, чья единственная работа — заставить своего единственного
    потребителя ходить через голый int и hydration-шим, купила бы изоляцию,
    которую некому нарушать, ценой FK и одного джойна вместо N+1. Когда
    появится второй домен (approvals маршрутизирует акт, mail шлёт письмо
    контактному лицу) — ``apps/tasks/interface.py`` расширяется аддитивно.

    В ``apps.hr`` не кладём сознательно: ``Employee.department`` и
    ``Employee.position`` — ``FK PROTECT NOT NULL``, а у сварщика внешнего
    подрядчика нет ни отдела, ни штатной должности. Синтетические записи
    испортили бы оргструктуру и все HR-отчёты, которые эти колонки читают.
    """

    name = models.CharField(max_length=255, unique=True)
    short_name = models.CharField(max_length=100, null=True, blank=True)
    # БИН (организация) или ИИН (ИП) — 12 цифр в Казахстане.
    bin_iin = models.CharField(max_length=12, null=True, blank=True, unique=True)
    contact_person = models.CharField(max_length=200, null=True, blank=True)
    phone = models.CharField(max_length=32, null=True, blank=True)
    email = models.CharField(max_length=255, null=True, blank=True)
    address = models.CharField(max_length=500, null=True, blank=True)
    notes = models.TextField(default="", blank=True, db_default="")
    status = models.CharField(
        max_length=20, choices=ContractorStatus.choices,
        default=ContractorStatus.ACTIVE, db_default=ContractorStatus.ACTIVE,
        db_index=True,
    )

    created_at = models.DateTimeField(auto_now_add=True, db_default=Now())
    updated_at = models.DateTimeField(auto_now=True, db_default=Now())

    class Meta:
        verbose_name = "Подрядчик"
        verbose_name_plural = "Подрядчики"

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Contractor id={self.id} name={self.name!r}>"


class ContractorWorker(models.Model):
    """Представитель подрядчика — носитель уровня допуска.

    ``user_id`` — ЗАГОТОВКА под будущий вход в систему. Сейчас его не
    заполняет ничто: ``apps.users`` о подрядчиках не знает, ``scope_for`` их
    не читает, ``roles_for`` не меняется. Форма колонки один в один с
    ``hr.Employee.user_id`` (nullable + unique): в Postgres это «сколько
    угодно NULL, но не более одной строки на аккаунт».

    ``position_title`` — свободный текст, а НЕ ``hr.Position``: должности
    подрядчика вне нашего штатного расписания, и заводить их там значило бы
    засорить справочник должностей чужими записями.
    """

    contractor = models.ForeignKey(Contractor, on_delete=models.PROTECT,
                                   related_name="workers")
    last_name = models.CharField(max_length=100)
    first_name = models.CharField(max_length=100)
    middle_name = models.CharField(max_length=100, null=True, blank=True)
    phone = models.CharField(max_length=32, null=True, blank=True)
    email = models.CharField(max_length=255, null=True, blank=True)
    position_title = models.CharField(max_length=200, null=True, blank=True)
    level = models.CharField(
        max_length=20, choices=ContractorLevel.choices,
        default=ContractorLevel.JUNIOR, db_default=ContractorLevel.JUNIOR,
        db_index=True,
    )
    user_id = models.IntegerField(null=True, blank=True, unique=True,
                                  db_index=True)
    is_active = models.BooleanField(default=True, db_default=True,
                                    db_index=True)

    created_at = models.DateTimeField(auto_now_add=True, db_default=Now())
    updated_at = models.DateTimeField(auto_now=True, db_default=Now())

    class Meta:
        verbose_name = "Работник подрядчика"
        verbose_name_plural = "Работники подрядчиков"

    @property
    def full_name(self) -> str:
        parts = [self.last_name, self.first_name, self.middle_name]
        return " ".join(p for p in parts if p).strip()

    def __repr__(self) -> str:  # pragma: no cover
        return (f"<ContractorWorker id={self.id} {self.full_name!r} "
                f"level={self.level}>")


class SiteStatus(models.TextChoices):
    ACTIVE = "active"        # работы идут
    SUSPENDED = "suspended"  # приостановлены
    CLOSED = "closed"        # объект сдан/закрыт


class Site(models.Model):
    """Объект (площадка) — физическое место работ: «Алга», «Сазаган».

    Живёт здесь, а не в отдельном аппе, по той же причине, что и
    ``Equipment``: единственные потребители — ``Project`` и ``Task``, оба в
    этом же аппе, так что настоящий FK (с ``select_related`` и ``PROTECT``)
    достаётся бесплатно. Вынести объект в свой апп означало бы голый
    ``IntegerField`` без ссылочной целостности плюс батч-резолв имён через
    ``hydration`` — тот самый налог Р2, который описан в шапке модуля, и
    платить его не за что, пока второго потребителя нет.

    Набор статусов повторяет ``Project.status`` намеренно: объект — такая
    же ось планирования, а не плоский справочник вида ``Equipment``.
    Отдельного ``is_active`` нет, чтобы не заводить два флага с
    пересекающимся смыслом.
    """

    name = models.CharField(max_length=200, unique=True)
    code = models.CharField(max_length=32, null=True, blank=True, unique=True)
    description = models.TextField(default="", blank=True, db_default="")
    address = models.CharField(max_length=500, null=True, blank=True)
    region = models.CharField(max_length=120, null=True, blank=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6,
                                   null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6,
                                    null=True, blank=True)
    status = models.CharField(
        max_length=20, choices=SiteStatus.choices,
        default=SiteStatus.ACTIVE, db_default=SiteStatus.ACTIVE,
        db_index=True,
    )
    color = models.CharField(max_length=20, default="#0ea5e9",
                             db_default="#0ea5e9")

    # Р2: hr/users владеют этими строками, FK нет.
    department_id = models.IntegerField(null=True, blank=True, db_index=True)
    manager_id = models.IntegerField(null=True, blank=True, db_index=True)

    created_at = models.DateTimeField(auto_now_add=True, db_default=Now())
    updated_at = models.DateTimeField(auto_now=True, db_default=Now())

    class Meta:
        verbose_name = "Площадка"
        verbose_name_plural = "Площадки"

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Site id={self.id} name={self.name!r}>"


class BlockStatus(models.TextChoices):
    PLANNED = "planned"      # ещё не начинали
    ACTIVE = "active"        # работы идут
    SUSPENDED = "suspended"  # приостановлены
    DONE = "done"            # блок сдан


class SiteBlock(models.Model):
    """Блок (участок) внутри объекта: у Сазагана это блок 1, блок 2, …

    Физическое деление площадки, по которому реально ведут работы: задача
    формулируется как «развезти 250 валов на блок I», а не «на Сазаган».
    Без этой таблицы номер блока оставался бы частью текста задачи, и ни
    сгруппировать работы по блокам, ни спросить «сколько осталось на блоке
    2» было бы нельзя.

    ``CASCADE`` от объекта, в отличие от ``PROTECT`` почти везде рядом:
    блок вне своей площадки не значит ничего — это не справочная строка,
    которую можно переиспользовать, а её часть. Сам объект при этом
    защищён от удаления через ``ProjectSite``, так что каскад срабатывает
    только когда площадку и правда сносят целиком.

    Плановые даты живут здесь, а объёмы — в ``SiteBlockVolume`` рядом:
    дата у блока одна, а видов работ на нём несколько.
    """

    site = models.ForeignKey(Site, on_delete=models.CASCADE,
                             related_name="blocks")
    name = models.CharField(max_length=120)
    code = models.CharField(max_length=32, null=True, blank=True)
    # Порядок обхода блоков на площадке. Не ``id``: блоки заводят пачкой и
    # потом вставляют забытый между вторым и третьим.
    order = models.PositiveSmallIntegerField(default=0, db_default=0)
    status = models.CharField(
        max_length=20, choices=BlockStatus.choices,
        default=BlockStatus.PLANNED, db_default=BlockStatus.PLANNED,
        db_index=True,
    )
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True, db_default=Now())
    updated_at = models.DateTimeField(auto_now=True, db_default=Now())

    class Meta:
        verbose_name = "Блок площадки"
        verbose_name_plural = "Блоки площадок"
        constraints = [
            # Уникальность в пределах площадки, а не глобально: «блок 1»
            # есть и на Сазагане, и на Алге, и это разные блоки.
            models.UniqueConstraint(fields=["site", "name"],
                                    name="uq_site_block_name"),
            models.UniqueConstraint(fields=["site", "code"],
                                    name="uq_site_block_code"),
            models.CheckConstraint(
                condition=models.Q(start_date__isnull=True)
                | models.Q(end_date__isnull=True)
                | models.Q(start_date__lte=models.F("end_date")),
                name="ck_site_block_dates",
            ),
        ]

    def __repr__(self) -> str:  # pragma: no cover
        return f"<SiteBlock id={self.id} site={self.site_id} name={self.name!r}>"


class SiteBlockVolume(models.Model):
    """Плановый объём работ на блоке: 250 валов на блок 1.

    Ради этой таблицы блок и заведён. Пока объём живёт только в тексте
    задачи, «сделано» приходится считать по статусам — задача либо done,
    либо нет. С плановым числом на блоке и фактическим на задачах
    (``TaskVolume``) процент выполнения считается по штукам, то есть так,
    как его считает прораб.

    Единица измерения не дублируется — она у ``WorkVolumeType``, иначе
    один и тот же вид работ на соседних блоках можно было бы завести в
    штуках и в тоннах и потерять возможность их сложить.
    """

    block = models.ForeignKey(SiteBlock, on_delete=models.CASCADE,
                              related_name="volumes")
    volume_type = models.ForeignKey(WorkVolumeType, on_delete=models.PROTECT,
                                    related_name="block_volumes")
    planned_quantity = models.DecimalField(max_digits=12, decimal_places=2)

    created_at = models.DateTimeField(auto_now_add=True, db_default=Now())
    updated_at = models.DateTimeField(auto_now=True, db_default=Now())

    class Meta:
        verbose_name = "Объём по блоку"
        verbose_name_plural = "Объёмы по блокам"
        constraints = [
            models.UniqueConstraint(fields=["block", "volume_type"],
                                    name="uq_site_block_volume"),
            models.CheckConstraint(
                condition=models.Q(planned_quantity__gte=0),
                name="ck_site_block_volume_non_negative",
            ),
        ]

    def __repr__(self) -> str:  # pragma: no cover
        return (f"<SiteBlockVolume block={self.block_id} "
                f"type={self.volume_type_id} qty={self.planned_quantity}>")


class Project(models.Model):
    """Проект — верхний уровень иерархии работ.

    Ниже него: объекты (``Site`` через ``ProjectSite``), на объектах —
    роудмапы (``Roadmap``), в роудмапах — задачи. Раньше здесь стояло
    «Roadmap-level project grouping tasks», и до появления ``Roadmap``
    отдельной таблицей это было правдой: проект и был единственным уровнем
    группировки. Теперь роудмап — своя сущность, и старая формулировка
    прямо противоречила бы модели.

    Projects are durable business initiatives ("Onboarding revamp") rather
    than software releases — there is no version/release_date semantics.
    A task with ``project=None`` is a standalone work item, a first-class
    state the UI renders differently.

    ``task_count`` / ``done_count`` / ``progress`` were ``ClassVar``
    scratch-space on the SQLAlchemy model, filled by the repository. They are
    not model state and live in the response builder here instead.
    """

    name = models.CharField(max_length=200, unique=True)
    description = models.TextField(default="", blank=True, db_default="")
    status = models.CharField(
        max_length=20, choices=ProjectStatus.choices,
        default=ProjectStatus.ACTIVE, db_default=ProjectStatus.ACTIVE,
    )
    color = models.CharField(max_length=20, default="#3b82f6", db_default="#3b82f6")
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)

    # Чем меряются длительности плана и факта: календарными днями или
    # рабочими по производственному календарю.
    #
    # По умолчанию FALSE — календарные, и это не «безопасный дефолт», а
    # предметное решение: стройка идёт 7/7. Раньше рабочие дни были зашиты
    # безальтернативно, и это ВРАЛО в цифрах: план «4 недели», введённый как
    # 28, против фактического размаха ровно в 4 календарные недели давал
    # 20 рабочих дней факта и «опережение на 8 дней» там, где идут точно по
    # плану. Офисным проектам, где выходные и правда не работают, флаг
    # включают вручную.
    use_production_calendar = models.BooleanField(
        default=False, db_default=False,
        help_text="Считать сроки в рабочих днях (по производственному "
                  "календарю), а не в календарных.",
    )

    # Р2: FK-less — users/hr own these rows, resolved via their interface.
    owner_id = models.IntegerField(null=True, blank=True, db_index=True)
    department_id = models.IntegerField(null=True, blank=True, db_index=True)

    # Объекты, на которых идёт проект. Многие-ко-многим, а не FK на Site:
    # один объект обслуживает несколько проектов, в том числе
    # последовательно во времени. FK заставил бы заводить «Алгу» заново под
    # каждый проект, и справочник рассыпался бы.
    sites = models.ManyToManyField(Site, through="ProjectSite",
                                   related_name="projects", blank=True)

    created_at = models.DateTimeField(auto_now_add=True, db_default=Now())
    updated_at = models.DateTimeField(auto_now=True, db_default=Now())

    class Meta:
        verbose_name = "Проект"
        verbose_name_plural = "Проекты"

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Project id={self.id} name={self.name!r}>"


class ProjectSite(models.Model):
    """Объект в составе проекта.

    Явная through-модель, а не автотаблица Django: связь несёт признак
    основного объекта и период присутствия проекта на нём — так «подрядчик
    ушёл с объекта в марте» выражается без удаления истории. Прецедент —
    ``TaskDepartmentLink`` ниже.

    ``PROTECT`` на объекте: пока объект числится в проекте, удалить его
    нельзя. Это и есть нужная гарантия целостности — сервисный слой
    отказывает раньше (409), а констрейнт остаётся страховкой на уровне БД.
    """

    project = models.ForeignKey(Project, on_delete=models.CASCADE,
                                related_name="site_links")
    site = models.ForeignKey(Site, on_delete=models.PROTECT,
                             related_name="project_links")
    is_primary = models.BooleanField(default=False, db_default=False)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True, db_default=Now())
    updated_at = models.DateTimeField(auto_now=True, db_default=Now())

    class Meta:
        verbose_name = "Площадка проекта"
        verbose_name_plural = "Площадки проектов"
        constraints = [
            models.UniqueConstraint(fields=["project", "site"],
                                    name="uq_project_site"),
            models.CheckConstraint(
                condition=models.Q(start_date__isnull=True)
                | models.Q(end_date__isnull=True)
                | models.Q(start_date__lte=models.F("end_date")),
                name="ck_project_site_dates",
            ),
        ]

    def __repr__(self) -> str:  # pragma: no cover
        return f"<ProjectSite project={self.project_id} site={self.site_id}>"


class RoadmapStatus(models.TextChoices):
    ACTIVE = "active"
    COMPLETED = "completed"
    ARCHIVED = "archived"


class Roadmap(models.Model):
    """Роудмап — пакет работ на блоке: «развозка валов трекерных конструкций».

    Уровень между блоком и задачей. Проект отвечает на «что строим», площадка
    — «где», блок — «на каком участке», роудмап — «какой вид работ», задача —
    «какая порция, кем и когда». Без него всё, что крупнее одной задачи,
    приходилось вести названием («развозка валов — 1», «развозка валов — 2»)
    и складывать глазами.

    ``project`` — ``CASCADE`` (как ``ContractorEngagement.project``:
    ``project_service.delete_project`` удаляет жёстко, и роудмап удалённого
    проекта смысла не имеет). ``site_block`` — ``PROTECT`` и NOT NULL:
    роудмап всегда живёт на блоке, а блок, на котором запланированы работы,
    удалять нельзя.

    **Площадки отдельным полем здесь НЕТ.** Она выводится джойном
    ``site_block__site``; хранить её ещё и колонкой значило бы завести второй
    источник правды, который разойдётся при первом же переносе блока.
    А ``project`` полем нужен и остаётся: блок его НЕ определяет — площадка
    связана с проектами через M2M ``ProjectSite``, и одна и та же площадка
    (а значит и блок) обслуживает несколько проектов.

    Правило «площадка блока входит в объекты проекта» живёт в
    ``roadmap_service.require_project_block``, а не в БД: оно про четыре
    таблицы, CheckConstraint видит одну строку одной. Тот же приём, что у
    ``resolve_task_site``.

    ``planned_*`` — это ПЛАН, введённый руками («4 недели, 2 человека, 2
    кары»). Факт нигде здесь не хранится: он считается свёрткой задач в
    ``roadmap_service.roadmap_metrics``, и хранить его копией значило бы
    завести второй источник правды, который разойдётся с первым.
    Человеческие ресурсы и техника в плане — не поля, а строки
    ``ResourceRequirement``: их несколько и они разнотипные.
    """

    project = models.ForeignKey(Project, on_delete=models.CASCADE,
                                related_name="roadmaps")
    site_block = models.ForeignKey("SiteBlock", on_delete=models.PROTECT,
                                   related_name="roadmaps")
    name = models.CharField(max_length=200)
    description = models.TextField(default="", blank=True, db_default="")
    status = models.CharField(
        max_length=20, choices=RoadmapStatus.choices,
        default=RoadmapStatus.ACTIVE, db_default=RoadmapStatus.ACTIVE,
        db_index=True,
    )
    color = models.CharField(max_length=20, default="#8b5cf6",
                             db_default="#8b5cf6")
    order = models.PositiveSmallIntegerField(default=0, db_default=0)

    # План по срокам. ``planned_working_days`` рядом с датами, а не вместо
    # них: «4 недели» на доске это длительность, а когда именно они лягут —
    # отдельный вопрос, и на момент планирования ответа на него может не
    # быть.
    planned_start_date = models.DateField(null=True, blank=True)
    planned_end_date = models.DateField(null=True, blank=True)
    planned_working_days = models.IntegerField(null=True, blank=True)

    # Р2: FK-less — users/hr владеют этими строками.
    owner_id = models.IntegerField(null=True, blank=True, db_index=True)
    department_id = models.IntegerField(null=True, blank=True, db_index=True)

    created_at = models.DateTimeField(auto_now_add=True, db_default=Now())
    updated_at = models.DateTimeField(auto_now=True, db_default=Now())

    class Meta:
        verbose_name = "Дорожная карта"
        verbose_name_plural = "Дорожные карты"
        constraints = [
            # Уникальность в пределах пары проект+блок: «развозка валов»
            # законно идёт и на блоке 1, и на блоке 2, и это разные пакеты.
            models.UniqueConstraint(fields=["project", "site_block", "name"],
                                    name="uq_roadmap_name"),
            models.CheckConstraint(
                condition=models.Q(planned_start_date__isnull=True)
                | models.Q(planned_end_date__isnull=True)
                | models.Q(planned_start_date__lte=models.F("planned_end_date")),
                name="ck_roadmap_planned_dates",
            ),
        ]

    def __repr__(self) -> str:  # pragma: no cover
        return (f"<Roadmap id={self.id} project={self.project_id} "
                f"block={self.site_block_id} name={self.name!r}>")


class ContractorEngagement(models.Model):
    """Привлечение подрядчика: кто, на какой проект/объект, в какие сроки.

    Пара «организация + объект» — ровно та единица, в которой сформулировано
    право senior «видеть все задачи своей организации по объекту», поэтому
    из этой строки вырастет скоуп видимости, когда появятся учётки.

    Все три целевых поля nullable при CHECK «хотя бы одно» — это покрывает
    реальные случаи: подрядчик на объекте вне конкретного проекта (только
    site), подрядчик на проекте целиком, то есть на всех его объектах
    (только project), подрядчик на конкретной паре, и подрядчик, взятый на
    один пакет работ (roadmap) — «развозку валов отдали субподряду, монтаж
    делаем сами».

    ``PROTECT`` на организации и объекте: привлечение архивируют
    (``is_active=False``), а не теряют молча вместе со справочной строкой.
    ``CASCADE`` на проекте — ``project_service.delete_project`` делает
    жёсткое удаление, и привлечение к удалённому проекту смысла не имеет.
    """

    contractor = models.ForeignKey(Contractor, on_delete=models.PROTECT,
                                   related_name="engagements")
    project = models.ForeignKey(Project, on_delete=models.CASCADE,
                                null=True, blank=True,
                                related_name="contractor_engagements")
    site = models.ForeignKey(Site, on_delete=models.PROTECT,
                             null=True, blank=True,
                             related_name="contractor_engagements")
    # ``CASCADE`` вслед за проектом: роудмап живёт внутри проекта, и
    # привлечение к исчезнувшему пакету работ ничего не значит.
    roadmap = models.ForeignKey("Roadmap", on_delete=models.CASCADE,
                                null=True, blank=True,
                                related_name="contractor_engagements")
    contract_no = models.CharField(max_length=64, null=True, blank=True)
    scope = models.TextField(default="", blank=True, db_default="")
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True, db_default=True,
                                    db_index=True)

    created_at = models.DateTimeField(auto_now_add=True, db_default=Now())
    updated_at = models.DateTimeField(auto_now=True, db_default=Now())

    class Meta:
        verbose_name = "Привлечение подрядчика"
        verbose_name_plural = "Привлечения подрядчиков"
        constraints = [
            # nulls_distinct=False — иначе констрейнт бесполезен ровно там,
            # где он нужнее всего. В SQL два NULL считаются РАЗНЫМИ, так что
            # обычный UNIQUE пропустил бы сколько угодно копий
            # (подрядчик, NULL, объект) — а это самый частый случай:
            # привлечение на объект вне конкретного проекта.
            # Postgres 15+ (здесь 16) и Django 5.0+ это поддерживают.
            models.UniqueConstraint(
                fields=["contractor", "project", "site", "roadmap"],
                name="uq_contractor_engagement", nulls_distinct=False),
            models.CheckConstraint(
                condition=models.Q(project__isnull=False)
                | models.Q(site__isnull=False)
                | models.Q(roadmap__isnull=False),
                name="ck_engagement_target",
            ),
            models.CheckConstraint(
                condition=models.Q(start_date__isnull=True)
                | models.Q(end_date__isnull=True)
                | models.Q(start_date__lte=models.F("end_date")),
                name="ck_engagement_dates",
            ),
        ]

    def __repr__(self) -> str:  # pragma: no cover
        return (f"<ContractorEngagement contractor={self.contractor_id} "
                f"project={self.project_id} site={self.site_id}>")


# ─────────────────────────────────────────────────────────────────────────
# Core entity
# ─────────────────────────────────────────────────────────────────────────

class Task(models.Model):
    """Main task entity with lifecycle management.

    The model intentionally blends Jira and SharePoint semantics:

    * Jira side — ``key``, task type, FSM ``status``, links (blocks /
      relates_to / duplicates), labels, activity log, hierarchy via
      ``parent``.
    * SharePoint side — ``supervisor_id`` (task owner who can delegate),
      delegates (deputies who edit on the supervisor's behalf), watchers
      (followers), ``progress_percent``, multi-assignee with primary +
      collaborator roles.
    """

    key = models.CharField(max_length=20, unique=True, db_index=True)
    summary = models.CharField(max_length=500)
    description = models.TextField(default="", blank=True, db_default="")

    # Classification. SET_NULL so deleting a custom type never cascades into
    # task rows; the response layer falls back to the "task" slug.
    task_type = models.ForeignKey(
        TaskType, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="tasks",
    )
    priority = models.CharField(
        max_length=20, choices=Priority.choices,
        default=Priority.MEDIUM, db_default=Priority.MEDIUM,
    )
    status = models.CharField(
        max_length=20, choices=Status.choices,
        default=Status.TODO, db_default=Status.TODO, db_index=True,
    )

    # SharePoint-style progress. Independent of status — a task can be 70 %
    # done while still in_review, and 100 % does not auto-Done it.
    progress_percent = models.SmallIntegerField(default=0, db_default=0)

    # Р2: FK-less participant ids (see module docstring).
    reporter_id = models.IntegerField(null=True, blank=True, db_index=True)
    # Denormalised pointer to the **primary** assignee for fast filters and
    # Kanban-card display. Source of truth for the full crew is TaskAssignee.
    assignee_id = models.IntegerField(null=True, blank=True, db_index=True)
    supervisor_id = models.IntegerField(null=True, blank=True, db_index=True)
    # Primary department; the full cross-functional set is TaskDepartmentLink.
    department_id = models.IntegerField(null=True, blank=True, db_index=True)

    project = models.ForeignKey(
        Project, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="tasks",
    )
    # Роудмап — пакет работ, в который входит задача. ``SET_NULL`` зеркалит
    # ``project``/``site``. Nullable и останется таким: у исторических задач
    # роудмапа нет и не будет (выводить его не из чего), а офисная задача
    # законно живёт вне производственного плана.
    #
    # ``project``/``site``/``site_block`` при этом НЕ отменяются в пользу
    # джойна через роудмап (``roadmap.project``, ``roadmap.site_block__site``):
    # задача может висеть на проекте без роудмапа (так живут все
    # существующие), и денормализация — то, на чём стоят фильтры и права
    # видимости. Согласованность держит
    # ``roadmap_service.resolve_task_roadmap``.
    roadmap = models.ForeignKey(
        "Roadmap", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="tasks",
    )
    # Объект работ. ``SET_NULL`` зеркалит ``project``: удаление справочной
    # строки никогда не каскадит в задачи. Nullable, потому что у
    # исторических задач объекта нет (бэкфилла быть не может — вывести его
    # не из чего), и потому что офисная задача законно без объекта.
    # Правило «объект задачи входит в объекты её проекта» живёт в
    # ``services/site_service.resolve_task_site``: оно охватывает три
    # таблицы, а CheckConstraint видит одну строку одной таблицы.
    site = models.ForeignKey(
        Site, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="tasks",
    )
    # Блок объекта — «развезти 250 валов на блок I». У задачи с роудмапом
    # это ЕГО блок (``Roadmap.site_block``), проставленный сюда
    # денормализацией: пакет работ живёт на одном блоке, и задача не может
    # оказаться на другом. Поле остаётся своим, а не выводится джойном,
    # потому что задача законно живёт и без роудмапа — тогда блок ставят
    # прямо на ней. Согласованность тройки проект/площадка/блок держит
    # ``roadmap_service.resolve_task_roadmap``, а правило «блок задачи
    # принадлежит объекту задачи» — ``site_service.resolve_task_block``:
    # оно про две таблицы, а CheckConstraint видит одну строку одной.
    site_block = models.ForeignKey(
        "SiteBlock", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="tasks",
    )
    # Кто выполняет. Оба NULL = своя команда. ``contractor_worker`` — это то,
    # что делает будущее правило junior «только свои задачи» выражаемым уже
    # сейчас: назначение это данные, вход это авторизация, и первое можно
    # вести задолго до второго.
    contractor = models.ForeignKey(
        "Contractor", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="tasks",
    )
    contractor_worker = models.ForeignKey(
        "ContractorWorker", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="tasks",
    )
    parent = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="subtasks",
    )

    due_date = models.DateField(null=True, blank=True)
    start_date = models.DateField(null=True, blank=True)
    estimated_working_days = models.IntegerField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    is_deleted = models.BooleanField(default=False, db_default=False, db_index=True)

    labels = models.ManyToManyField(Label, related_name="tasks", blank=True)

    created_at = models.DateTimeField(auto_now_add=True, db_default=Now())
    updated_at = models.DateTimeField(auto_now=True, db_default=Now())

    class Meta:
        verbose_name = "Задача"
        verbose_name_plural = "Задачи"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(start_date__isnull=True)
                | models.Q(due_date__isnull=True)
                | models.Q(start_date__lte=models.F("due_date")),
                name="ck_task_dates",
            ),
        ]

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Task id={self.id} key={self.key!r} status={self.status}>"

    # ── FSM ──────────────────────────────────────────────────────────────
    def can_transition_to(self, target: str) -> bool:
        """Whether ``target`` is reachable from the current status."""
        return target in TRANSITIONS.get(self.status, frozenset())

    def apply_transition(self, target: str) -> None:
        """Apply a status transition, validating it against ``TRANSITIONS``.

        Mirrors the FastAPI original including its side effects: entering a
        terminal status stamps ``completed_at`` (only if unset), leaving one
        clears it so analytics stay honest, and reaching ``done`` forces
        progress to 100 %.
        """
        if not self.can_transition_to(target):
            raise ValueError(
                f"Cannot transition from {self.status} to {target}. "
                f"Allowed: {set(TRANSITIONS.get(self.status, frozenset()))}"
            )
        self.status = target
        if target in TERMINAL_STATUSES:
            if not self.completed_at:
                self.completed_at = timezone.now()
        else:
            # Re-opened — drop the completion stamp.
            self.completed_at = None
        if target == Status.DONE:
            self.progress_percent = 100


class TaskDepartmentLink(models.Model):
    """A task may span several departments (cross-functional work).

    ``Task.department_id`` stays the primary department; this junction holds
    the full set. The original was a bare M2M table into the
    ``task_departments`` replica — with that replica gone (Р2) the far side
    is a plain hr-owned id, so this must be an explicit model rather than a
    Django ``ManyToManyField``.
    """

    task = models.ForeignKey(Task, on_delete=models.CASCADE,
                             related_name="department_links")
    department_id = models.IntegerField(db_index=True)

    class Meta:
        verbose_name = "Отдел задачи"
        verbose_name_plural = "Отделы задач"
        constraints = [
            models.UniqueConstraint(fields=["task", "department_id"],
                                    name="uq_task_department_link"),
        ]


# ─────────────────────────────────────────────────────────────────────────
# Participants — multi-assignee, delegates, watchers
# ─────────────────────────────────────────────────────────────────────────

class TaskAssignee(models.Model):
    """One worker on a task, with a role.

    The ``primary`` row is mirrored into ``Task.assignee_id`` for fast
    filter/joins and Kanban-card avatars.
    """

    task = models.ForeignKey(Task, on_delete=models.CASCADE,
                             related_name="assignees")
    user_id = models.IntegerField(db_index=True)
    role = models.CharField(
        max_length=20, choices=AssigneeRole.choices,
        default=AssigneeRole.COLLABORATOR, db_default=AssigneeRole.COLLABORATOR,
    )
    assigned_at = models.DateTimeField(auto_now_add=True, db_default=Now())

    class Meta:
        verbose_name = "Исполнитель задачи"
        verbose_name_plural = "Исполнители задач"
        constraints = [
            models.UniqueConstraint(fields=["task", "user_id"],
                                    name="uq_task_assignee"),
        ]


class TaskDelegate(models.Model):
    """Supervisor's deputy on a task — may edit as if they were the supervisor.

    ``granted_by_id`` is who created the delegation (almost always the
    supervisor, but an elevated admin can also push one), kept so the
    activity log can attribute a change to a delegate vs. the supervisor.
    """

    task = models.ForeignKey(Task, on_delete=models.CASCADE,
                             related_name="delegates")
    user_id = models.IntegerField(db_index=True)
    granted_by_id = models.IntegerField(null=True, blank=True)
    granted_at = models.DateTimeField(auto_now_add=True, db_default=Now())

    class Meta:
        verbose_name = "Делегат задачи"
        verbose_name_plural = "Делегаты задач"
        constraints = [
            models.UniqueConstraint(fields=["task", "user_id"],
                                    name="uq_task_delegate"),
        ]


class TaskWatcher(models.Model):
    """Follower — no edit rights, but sees the task in lists and is notified."""

    task = models.ForeignKey(Task, on_delete=models.CASCADE,
                             related_name="watchers")
    user_id = models.IntegerField(db_index=True)
    subscribed_at = models.DateTimeField(auto_now_add=True, db_default=Now())

    class Meta:
        verbose_name = "Наблюдатель задачи"
        verbose_name_plural = "Наблюдатели задач"
        constraints = [
            models.UniqueConstraint(fields=["task", "user_id"],
                                    name="uq_task_watcher"),
        ]


# ─────────────────────────────────────────────────────────────────────────
# Task-attached records
# ─────────────────────────────────────────────────────────────────────────

class TaskVolume(models.Model):
    """ПЛАНОВЫЙ объём работ по задаче: «развезти 250 валов».

    Число, а не текст внутри ``summary`` — именно это делает выполнение
    измеримым в штуках.

    **Факта здесь нет.** Раньше рядом лежало ``completed_quantity``, и это
    было число без даты и без автора: нельзя было сказать ни когда работу
    сделали, ни кто отчитался, ни что цифру потом правили. Факт переехал в
    ``DailyReport`` — по строке на смену, с датой ВЫПОЛНЕНИЯ работ, — и
    считается суммой: ``Σ DailyReport.quantity`` по паре (задача, вид
    работ). Один источник правды; кэша обратно не завели специально, чтобы
    ему нечего было рассинхронизировать.
    """

    task = models.ForeignKey(Task, on_delete=models.CASCADE,
                             related_name="volumes")
    volume_type = models.ForeignKey(WorkVolumeType, on_delete=models.PROTECT,
                                    related_name="task_volumes")
    planned_quantity = models.DecimalField(max_digits=12, decimal_places=2)

    created_at = models.DateTimeField(auto_now_add=True, db_default=Now())
    updated_at = models.DateTimeField(auto_now=True, db_default=Now())

    class Meta:
        verbose_name = "Объём работ"
        verbose_name_plural = "Объёмы работ"
        constraints = [
            models.UniqueConstraint(fields=["task", "volume_type"],
                                    name="uq_task_volume"),
            models.CheckConstraint(
                condition=models.Q(planned_quantity__gte=0),
                name="ck_task_volume_non_negative",
            ),
        ]

    def __repr__(self) -> str:  # pragma: no cover
        return (f"<TaskVolume task={self.task_id} type={self.volume_type_id} "
                f"plan={self.planned_quantity}>")


class DailyReport(models.Model):
    """Ежедневный отчёт: сколько сделали, по какому виду работ и КОГДА.

    Единственный источник факта выполнения. Ключевая колонка —
    ``work_date``, дата ВЫПОЛНЕНИЯ работ, и она принципиально не то же
    самое, что ``created_at`` (дата заполнения): отчёт за пятницу
    заполняют в понедельник, и S-кривая обязана положить его на пятницу.
    Без этого различия нет ни отслеживания по дням, ни прогноза темпа.

    ``volume_type`` — отступление от SPEC §3.1, и оно вынужденное. Спека
    кладёт на задачу один ``planned_quantity`` + ``unit``, поэтому её
    отчёту хватает голого числа. У нас объёмы нормализованы
    (``TaskVolume`` по видам работ), значит отчёт обязан называть вид:
    иначе «сделано 40» на задаче с валами и конструкциями не к чему
    отнести. Когда вид у задачи один — форма подставляет его сама.

    ``UNIQUE(task, work_date)`` НЕТ намеренно: за день бывает несколько
    смен и несколько бригадиров, их отчёты складываются.

    ``is_deleted`` вместо удаления — как у ``Task``: удалённый отчёт это
    исправленная отчётность, и она должна оставаться видимой.
    """

    task = models.ForeignKey(Task, on_delete=models.CASCADE,
                             related_name="daily_reports")
    volume_type = models.ForeignKey(WorkVolumeType, on_delete=models.PROTECT,
                                    related_name="daily_reports")
    # Р2: автор — users id из JWT, FK нет.
    author_id = models.IntegerField(null=True, blank=True, db_index=True)
    work_date = models.DateField(db_index=True)
    quantity = models.DecimalField(max_digits=12, decimal_places=2)
    headcount = models.PositiveSmallIntegerField(null=True, blank=True)
    comment = models.TextField(default="", blank=True, db_default="")

    # Денормализованный номер текущей ревизии. Обычное число, а не FK на
    # ``DailyReportRevision``: FK был бы круговым (ревизия ссылается на
    # отчёт), и Django пришлось бы разводить их двумя миграциями. Тот же
    # приём и по той же причине, что у
    # ``approvals.RequestFormTemplate.current_version_id``.
    current_revision = models.PositiveSmallIntegerField(default=1, db_default=1)
    is_deleted = models.BooleanField(default=False, db_default=False,
                                     db_index=True)

    created_at = models.DateTimeField(auto_now_add=True, db_default=Now())
    updated_at = models.DateTimeField(auto_now=True, db_default=Now())

    class Meta:
        verbose_name = "Ежедневный отчёт"
        verbose_name_plural = "Ежедневные отчёты"
        indexes = [
            models.Index(fields=["task", "work_date"],
                         name="ix_daily_report_task_date"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(quantity__gte=0),
                name="ck_daily_report_quantity_non_negative",
            ),
        ]

    def __repr__(self) -> str:  # pragma: no cover
        return (f"<DailyReport task={self.task_id} {self.work_date} "
                f"qty={self.quantity} rev={self.current_revision}>")


class DailyReportRevision(models.Model):
    """Снимок отчёта на момент версии — «аналог Git» из ТЗ.

    Полная копия полей, а не пара old/new как в ``TaskActivity``: правку
    отчёта читают целиком («что было в версии 2»), а не по одному полю, и
    собирать состояние из цепочки дельт ради каждого показа значило бы
    считать одно и то же заново. Прецедент в репозитории —
    ``approvals.RequestFormTemplateVersion``.

    Строки неизменяемы: правка отчёта добавляет НОВУЮ ревизию, а не
    переписывает старую. Мягкое удаление отчёта ревизии не создаёт — это
    не изменение содержания, и факт виден по ``DailyReport.is_deleted``.
    """

    report = models.ForeignKey(DailyReport, on_delete=models.CASCADE,
                               related_name="revisions")
    revision_no = models.PositiveSmallIntegerField()

    # Снимок. Вид работ сюда не копируется: сменить его — это другой отчёт,
    # а не другая версия этого, и сервис такую правку не принимает.
    work_date = models.DateField()
    quantity = models.DecimalField(max_digits=12, decimal_places=2)
    headcount = models.PositiveSmallIntegerField(null=True, blank=True)
    comment = models.TextField(default="", blank=True, db_default="")

    edited_by_id = models.IntegerField(null=True, blank=True)
    edited_at = models.DateTimeField(auto_now_add=True, db_default=Now())

    class Meta:
        verbose_name = "Версия отчёта"
        verbose_name_plural = "Версии отчётов"
        ordering = ["revision_no"]
        constraints = [
            models.UniqueConstraint(fields=["report", "revision_no"],
                                    name="uq_daily_report_revision"),
        ]

    def __repr__(self) -> str:  # pragma: no cover
        return (f"<DailyReportRevision report={self.report_id} "
                f"rev={self.revision_no}>")


class TaskComment(models.Model):
    task = models.ForeignKey(Task, on_delete=models.CASCADE,
                             related_name="comments")
    author_id = models.IntegerField(null=True, blank=True)
    body = models.TextField()

    created_at = models.DateTimeField(auto_now_add=True, db_default=Now())
    updated_at = models.DateTimeField(auto_now=True, db_default=Now())

    class Meta:
        verbose_name = "Комментарий к задаче"
        verbose_name_plural = "Комментарии к задачам"


class TaskAttachment(models.Model):
    """File attached to a task.

    ``file_path`` is the storage key handed back by
    ``apps.media_files.interface.store_file`` (Р3 — no S2S upload call).
    """

    task = models.ForeignKey(Task, on_delete=models.CASCADE,
                             related_name="attachments")
    file_path = models.CharField(max_length=500)
    filename = models.CharField(max_length=255)
    uploaded_by_id = models.IntegerField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True, db_default=Now())
    updated_at = models.DateTimeField(auto_now=True, db_default=Now())

    class Meta:
        verbose_name = "Вложение задачи"
        verbose_name_plural = "Вложения задач"


class TaskActivity(models.Model):
    """Append-only log of task field changes."""

    task = models.ForeignKey(Task, on_delete=models.CASCADE,
                             related_name="activities")
    actor_id = models.IntegerField(null=True, blank=True)
    field_name = models.CharField(max_length=50)
    old_value = models.TextField(null=True, blank=True)
    new_value = models.TextField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True, db_default=Now())
    updated_at = models.DateTimeField(auto_now=True, db_default=Now())

    class Meta:
        verbose_name = "Событие задачи"
        verbose_name_plural = "События задач"


class TaskLink(models.Model):
    """Directed relationship between two tasks."""

    source = models.ForeignKey(Task, on_delete=models.CASCADE,
                               related_name="outgoing_links")
    target = models.ForeignKey(Task, on_delete=models.CASCADE,
                               related_name="incoming_links")
    link_type = models.CharField(max_length=20, choices=LinkType.choices)
    created_by_id = models.IntegerField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True, db_default=Now())
    updated_at = models.DateTimeField(auto_now=True, db_default=Now())

    class Meta:
        verbose_name = "Связь задач"
        verbose_name_plural = "Связи задач"
        constraints = [
            models.UniqueConstraint(fields=["source", "target", "link_type"],
                                    name="uq_task_link"),
            # The original enforced "no self-link" in the model's __init__,
            # which only covered ORM construction. A CHECK covers every write
            # path — same rule, one layer lower.
            models.CheckConstraint(
                condition=~models.Q(source=models.F("target")),
                name="ck_task_link_not_self",
            ),
        ]


class ResourceKind(models.TextChoices):
    HUMAN = "human", "Человек"
    EQUIPMENT = "equipment", "Техника"


class ResourceRequirement(models.Model):
    """Потребность в ресурсе КОЛИЧЕСТВОМ: «2 человека», «2 кары».

    План на доске сформулирован числами, а не именами: на этапе
    планирования пакета работ известно, что нужны две кары, и неизвестно,
    какие именно. Именные назначения — соседняя таблица
    ``ResourceAllocation``; связь между ними необязательная, потому что
    план и факт живут в разное время.

    Висит на роудмапе ИЛИ на задаче — ровно одном из двух. Обе оси доски
    («график работ / человеческие ресурсы / учёт техники» повторены и на
    роудмапе, и на задаче) выражаются одной таблицей: два набора почти
    одинаковых колонок разошлись бы при первой же правке.

    ``work_role`` и ``equipment_category`` оба nullable: «нужно 2 человека,
    роль не важна» — законная потребность, и заставлять выбирать роль ради
    строчки в плане значит выдумывать данные.
    """

    roadmap = models.ForeignKey("Roadmap", on_delete=models.CASCADE,
                                null=True, blank=True,
                                related_name="requirements")
    task = models.ForeignKey(Task, on_delete=models.CASCADE,
                             null=True, blank=True,
                             related_name="requirements")
    kind = models.CharField(max_length=20, choices=ResourceKind.choices,
                            db_index=True)
    work_role = models.ForeignKey(WorkRole, on_delete=models.PROTECT,
                                  null=True, blank=True,
                                  related_name="requirements")
    equipment_category = models.ForeignKey(
        EquipmentCategory, on_delete=models.PROTECT, null=True, blank=True,
        related_name="requirements")
    quantity = models.PositiveSmallIntegerField(default=1, db_default=1)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    note = models.CharField(max_length=255, null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True, db_default=Now())
    updated_at = models.DateTimeField(auto_now=True, db_default=Now())

    class Meta:
        verbose_name = "Потребность в ресурсе"
        verbose_name_plural = "Потребности в ресурсах"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(roadmap__isnull=True, task__isnull=False)
                | models.Q(roadmap__isnull=False, task__isnull=True),
                name="ck_requirement_exactly_one_target",
            ),
            # Поле «не своего» вида обязано быть пустым: потребность в людях
            # с проставленной категорией техники — это не полезная запись,
            # а мусор, который потом кто-то посчитает.
            models.CheckConstraint(
                condition=models.Q(kind=ResourceKind.HUMAN,
                                   equipment_category__isnull=True)
                | models.Q(kind=ResourceKind.EQUIPMENT,
                           work_role__isnull=True),
                name="ck_requirement_kind_fields",
            ),
            models.CheckConstraint(
                condition=models.Q(start_date__isnull=True)
                | models.Q(end_date__isnull=True)
                | models.Q(start_date__lte=models.F("end_date")),
                name="ck_requirement_dates",
            ),
        ]

    def __repr__(self) -> str:  # pragma: no cover
        return (f"<ResourceRequirement kind={self.kind} x{self.quantity} "
                f"roadmap={self.roadmap_id} task={self.task_id}>")


class ResourceAllocation(models.Model):
    """Именное назначение ресурса: конкретный человек или конкретная машина.

    Раньше называлась ``TaskAssignment`` и умела висеть только на задаче.
    Переименована вместе с добавлением ``roadmap``: модель с именем
    «TaskAssignment» и внешним ключом на роудмап врала бы в названии. Один
    механизм на оба уровня означает ещё и то, что ресурсный Гант читает
    одну таблицу, а не склеивает две.

    Instead of a polymorphic ``(resource_type, resource_id)`` pair the
    original kept two nullable columns plus a CHECK enforcing that exactly
    one is set; that is preserved. ``employee_id`` lost its FK with the user
    replica (Р2); ``equipment`` keeps a real FK since Equipment is local.

    ⚠ ``employee_id`` хранит **users id**, а не PK строки ``hr.Employee``:
    ``gantt_service`` резолвит его через ``hydration.user_briefs``. Имя
    досталось от FastAPI-оригинала и переименование отложено сознательно —
    это отдельная миграция с правкой фронта, а не попутная.

    ``requirement`` связывает факт с планом («эта кара закрывает одну из
    двух запланированных»). Nullable: назначить ресурс, не планировав его
    заранее, — нормальный ход событий, а не нарушение.
    """

    task = models.ForeignKey(Task, on_delete=models.CASCADE,
                             null=True, blank=True,
                             related_name="resource_assignments")
    roadmap = models.ForeignKey("Roadmap", on_delete=models.CASCADE,
                                null=True, blank=True,
                                related_name="resource_assignments")
    # ``SET_NULL``: потребность можно снять с плана, не теряя того, кто уже
    # назначен и работает.
    requirement = models.ForeignKey(ResourceRequirement,
                                    on_delete=models.SET_NULL,
                                    null=True, blank=True,
                                    related_name="allocations")
    employee_id = models.IntegerField(null=True, blank=True, db_index=True)
    equipment = models.ForeignKey(Equipment, on_delete=models.CASCADE,
                                  null=True, blank=True,
                                  related_name="assignments")
    role = models.CharField(max_length=100, null=True, blank=True)
    # % of resource capacity, reserved for future overload analysis.
    allocation = models.IntegerField(default=100, db_default=100)

    created_at = models.DateTimeField(auto_now_add=True, db_default=Now())
    updated_at = models.DateTimeField(auto_now=True, db_default=Now())

    class Meta:
        verbose_name = "Выделение ресурса"
        verbose_name_plural = "Выделение ресурсов"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(employee_id__isnull=True,
                                   equipment__isnull=False)
                | models.Q(employee_id__isnull=False, equipment__isnull=True),
                name="ck_assignment_exactly_one_resource",
            ),
            models.CheckConstraint(
                condition=models.Q(task__isnull=True, roadmap__isnull=False)
                | models.Q(task__isnull=False, roadmap__isnull=True),
                name="ck_allocation_exactly_one_target",
            ),
            # nulls_distinct=False — иначе на роудмап-строках констрейнт
            # бесполезен: у них ``task`` всегда NULL, а два NULL в SQL
            # РАЗНЫЕ, и один и тот же человек лёг бы на пакет дважды.
            models.UniqueConstraint(
                fields=["task", "roadmap", "employee_id", "equipment"],
                name="uq_task_assignment", nulls_distinct=False),
        ]


# ─────────────────────────────────────────────────────────────────────────
# Notifications
# ─────────────────────────────────────────────────────────────────────────

class Notification(models.Model):
    """System notification for task / calendar / HR events.

    ``target_type`` + ``target_id`` is the canonical "click here to see what
    this is about" reference; the frontend maps the type to a route prefix
    (``task`` → /tasks/<id>, ``calendar_event`` → /calendar, ``employee`` →
    /hr/employees/<id>). ``task`` is the legacy FK kept for rows written
    before that generalisation — new code sets ``target_type='task'``.
    """

    recipient_id = models.IntegerField(db_index=True)
    actor_id = models.IntegerField(null=True, blank=True)
    task = models.ForeignKey(Task, on_delete=models.SET_NULL,
                             null=True, blank=True,
                             related_name="notifications")
    verb = models.CharField(max_length=200)
    is_read = models.BooleanField(default=False, db_default=False, db_index=True)
    # Snapshot of the actor's avatar at write time: the original took it so a
    # replica gap couldn't blank the toast's photo. Kept because it is also a
    # point-in-time record — a later avatar change should not rewrite history.
    actor_avatar_url = models.CharField(max_length=1024, null=True, blank=True)
    read_at = models.DateTimeField(null=True, blank=True)
    target_type = models.CharField(max_length=32, null=True, blank=True)
    target_id = models.IntegerField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True, db_default=Now())
    updated_at = models.DateTimeField(auto_now=True, db_default=Now())

    class Meta:
        verbose_name = "Уведомление"
        verbose_name_plural = "Уведомления"


# ─────────────────────────────────────────────────────────────────────────
# Sequences and the production calendar
# ─────────────────────────────────────────────────────────────────────────

class TaskSequence(models.Model):
    """Atomic counter behind task-key generation (``TASK-17``).

    Incremented under ``select_for_update()`` — see
    ``apps.tasks.services.sequence_service``. The row lock, not this model,
    is what makes concurrent creates collision-free.
    """

    name = models.CharField(max_length=50, unique=True)
    current_value = models.IntegerField(default=0, db_default=0)

    created_at = models.DateTimeField(auto_now_add=True, db_default=Now())
    updated_at = models.DateTimeField(auto_now=True, db_default=Now())

    class Meta:
        verbose_name = "Нумератор задач"
        verbose_name_plural = "Нумераторы задач"


class ProductionDay(models.Model):
    """One day of the production calendar (Kazakhstan).

    ``working_days_since_epoch`` is a running count of working days up to and
    including this date. It turns "deadline = start + N working days" into an
    O(1) indexed lookup instead of a day-by-day walk.
    """

    date = models.DateField(unique=True, db_index=True)
    # working | weekend | holiday | short
    day_type = models.CharField(max_length=20, default="working",
                                db_default="working")
    note = models.CharField(max_length=255, null=True, blank=True)
    working_days_since_epoch = models.IntegerField(db_index=True)

    created_at = models.DateTimeField(auto_now_add=True, db_default=Now())
    updated_at = models.DateTimeField(auto_now=True, db_default=Now())

    class Meta:
        verbose_name = "Производственный день"
        verbose_name_plural = "Производственные дни"


# ─────────────────────────────────────────────────────────────────────────
# Calendar
# ─────────────────────────────────────────────────────────────────────────

class CalendarEvent(models.Model):
    """Event in the shared calendar.

    Stores precise ``start_at``/``end_at``; ``is_all_day`` is a presentation
    hint — for true all-day events the form sends midnight–end-of-day and the
    UI hides the time component.
    """

    title = models.CharField(max_length=255)
    description = models.TextField(null=True, blank=True)
    start_at = models.DateTimeField(db_index=True)
    end_at = models.DateTimeField(db_index=True)
    is_all_day = models.BooleanField(default=True, db_default=True)
    # personal | department | common | conference
    event_type = models.CharField(max_length=20, default="personal",
                                  db_default="personal", db_index=True)
    conference_room_id = models.CharField(max_length=64, null=True, blank=True)
    color = models.CharField(max_length=20, null=True, blank=True)
    is_global = models.BooleanField(default=False, db_default=False)
    department_id = models.IntegerField(null=True, blank=True, db_index=True)
    # Author, taken from the JWT on create. Nullable so rows predating the
    # column survive a backfill.
    creator_id = models.IntegerField(null=True, blank=True, db_index=True)

    created_at = models.DateTimeField(auto_now_add=True, db_default=Now())
    updated_at = models.DateTimeField(auto_now=True, db_default=Now())

    class Meta:
        verbose_name = "Событие календаря"
        verbose_name_plural = "События календаря"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(event_type__in=["personal", "department",
                                                   "common", "conference"]),
                name="ck_calendar_event_type",
            ),
            models.CheckConstraint(
                condition=models.Q(end_at__gte=models.F("start_at")),
                name="ck_calendar_event_range",
            ),
        ]


class EventException(models.Model):
    """A cancelled occurrence of a recurring calendar event."""

    event = models.ForeignKey(CalendarEvent, on_delete=models.CASCADE,
                              related_name="exceptions")
    exception_date = models.DateField()
    is_cancelled = models.BooleanField(default=True, db_default=True)

    created_at = models.DateTimeField(auto_now_add=True, db_default=Now())
    updated_at = models.DateTimeField(auto_now=True, db_default=Now())

    class Meta:
        verbose_name = "Исключение события"
        verbose_name_plural = "Исключения событий"


class CalendarEventParticipant(models.Model):
    """Invitee of a calendar event.

    The original used a composite ``(event_id, user_id)`` primary key. Django
    grows a surrogate ``id`` here and the pair is enforced by a unique
    constraint instead — the pair is never exposed as an identifier by the
    API (participants are addressed by ``user_id`` within an event), so this
    is invisible to clients and keeps the row addressable by the admin.
    """

    event = models.ForeignKey(CalendarEvent, on_delete=models.CASCADE,
                              related_name="participants")
    user_id = models.IntegerField(db_index=True)
    # 'pending' until the invitee responds. The author is inserted as
    # 'accepted' — they implicitly attend their own event.
    rsvp_status = models.CharField(max_length=16, default="pending",
                                   db_default="pending")

    created_at = models.DateTimeField(auto_now_add=True, db_default=Now())

    class Meta:
        verbose_name = "Участник события"
        verbose_name_plural = "Участники событий"
        constraints = [
            models.UniqueConstraint(fields=["event", "user_id"],
                                    name="uq_calendar_event_participant"),
            models.CheckConstraint(
                condition=models.Q(rsvp_status__in=["pending", "accepted",
                                                    "declined"]),
                name="ck_calendar_event_participant_status",
            ),
        ]
