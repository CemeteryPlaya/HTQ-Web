"""Модели домена signoff — «Согласование».

Универсальный движок согласования: он ничего не знает про бюджеты, договоры
и вообще про предметные аппки. Объект, который согласуют, адресуется парой
``(subject_type, subject_id)`` — строка вида ``"contracts.budget"`` и id
строки в ЧУЖОЙ таблице. Ни ``ContentType``, ни межаппного FK здесь нет и
быть не может: правило репозитория (``apps/core/tests/test_app_isolation.py``)
запрещает signoff импортировать ``apps.contracts.models``, а ``ContentType``
дал бы обходной путь к тому же самому через ``content_type.model_class()``.

Как аппка узнаёт, что делать после согласования: предметная аппка сама
регистрирует свой тип в ``services/registry.py`` (из ``AppConfig.ready()``)
и передаёт колбэки. Зависимость направлена ОДНОСТОРОННЕ — contracts знает
про signoff, signoff про contracts не знает никогда.

Три слоя:

1. **Маршрут** — ``ApprovalRoute`` + ``ApprovalRouteStage`` +
   ``ApprovalRouteStageApprover``. Настройка: какие этапы и кто на них
   согласует. Ведётся администратором, меняется редко.
2. **Процесс** — ``ApprovalProcess`` + ``ApprovalProcessStage`` +
   ``ApprovalTask``. Живой экземпляр согласования конкретного объекта.
   Этапы процесса — СНИМОК маршрута на момент запуска (см. докстринг
   ``ApprovalProcessStage``).
3. ``ApprovalEvent`` — журнал: кто что решил и когда.

Параллельность выражена одним числом: ``order``. Этапы с ОДИНАКОВЫМ
``order`` идут параллельно, с разным — последовательно. Отдельной модели
графа (узлы/рёбра/условия) здесь нет намеренно: заказчику нужны «2, 3 или 5
этапов, параллельно или друг за другом», а это ровно то, что выражает
целочисленный порядок. Граф с условными переходами — другая задача, и
стоит она на порядок дороже (ср. ``apps.approvals``, 7 000 строк).

Отказ на любом этапе отклоняет ВЕСЬ процесс немедленно — это требование
заказчика и одновременно безопасное по умолчанию поведение.
"""

from django.db import models
from django.db.models import Q
from django.db.models.functions import Now


class Quorum(models.TextChoices):
    """Сколько согласующих этапа должны одобрить, чтобы этап прошёл."""

    ANY = "any", "Достаточно одного"
    ALL = "all", "Нужны все"


class ProcessState(models.TextChoices):
    PENDING = "pending", "На согласовании"
    APPROVED = "approved", "Согласовано"
    REJECTED = "rejected", "Отклонено"
    CANCELLED = "cancelled", "Отозвано"


class StageState(models.TextChoices):
    WAITING = "waiting", "Ожидает очереди"
    ACTIVE = "active", "На рассмотрении"
    APPROVED = "approved", "Согласован"
    REJECTED = "rejected", "Отклонён"
    # Этап, до которого дело не дошло: процесс отклонили или отозвали раньше.
    # Отдельно от «отклонён», чтобы в карточке было видно, КТО отказал, а кто
    # просто не успел получить запрос.
    SKIPPED = "skipped", "Не потребовался"


class TaskState(models.TextChoices):
    PENDING = "pending", "Ожидает решения"
    APPROVED = "approved", "Согласовано"
    REJECTED = "rejected", "Отклонено"
    SKIPPED = "skipped", "Не потребовалось"


class ApprovalState(models.TextChoices):
    """Состояние согласования ПРЕДМЕТНОГО объекта (поле примеси ``Approvable``).

    Дублирует ``ProcessState`` не полностью и намеренно: у объекта есть
    состояние «черновик» — процесс ещё не запускали, — которого у процесса
    быть не может, а «отозван» с точки зрения объекта неотличим от
    «черновик» (его снова можно отправить на согласование).
    """

    DRAFT = "draft", "Черновик"
    PENDING = "pending", "На согласовании"
    APPROVED = "approved", "Согласовано"
    REJECTED = "rejected", "Отклонено"


class ImproperlyConfiguredSubject(Exception):
    """Модель-наследник ``Approvable`` без ``SIGNOFF_SUBJECT_TYPE``."""


class Approvable(models.Model):
    """Примесь для предметной модели, которую можно отправить на согласование.

    Абстрактная — колонка ``approval_state`` появляется в таблице САМОЙ
    предметной модели (``contracts_budget`` и т.д.), никакого межаппного FK
    при этом не возникает.

    Импортируется соседями через ``apps.signoff.interface`` (единственное
    имя, которое чужая аппка имеет право импортировать):

        from apps.signoff import interface as signoff

        class Budget(signoff.Approvable, models.Model):
            SIGNOFF_SUBJECT_TYPE = "contracts.budget"

    ``approval_state`` — денормализация состояния процесса на сам объект.
    Хранится, а не вычисляется на каждом чтении, потому что предметные
    запросы фильтруют по нему постоянно («не показывать несогласованные
    бюджеты как источник денег»), а межаппный вызов в signoff на каждую
    строку списка — это N+1 через границу аппки. Единственный, кто это поле
    пишет, — колбэк из ``services/engine.py``, и пишет он его в ТОЙ ЖЕ
    транзакции, что и состояние процесса, поэтому разъехаться они не могут.
    """

    # Заполняется наследником. Должен совпадать с ключом, под которым
    # предметная аппка зарегистрировала себя в registry.
    SIGNOFF_SUBJECT_TYPE: str = ""

    approval_state = models.CharField(
        max_length=16, choices=ApprovalState.choices,
        default=ApprovalState.DRAFT, db_default=ApprovalState.DRAFT,
        db_index=True, verbose_name="Состояние согласования",
    )

    class Meta:
        abstract = True

    @property
    def is_approved(self) -> bool:
        return self.approval_state == ApprovalState.APPROVED

    def submit_for_approval(self, *, initiator_id: int | None = None):
        """Запустить согласование этого объекта. Возвращает ``ApprovalProcess``.

        Импорт локальный: ``services.engine`` импортирует эти модели, и
        импорт верхнего уровня замкнул бы цикл.
        """
        from apps.signoff.services import engine

        return engine.start(subject_type=self._subject_type(),
                            subject_id=self.pk, initiator_id=initiator_id)

    def approval_process(self):
        """Текущий (последний) процесс согласования объекта или ``None``."""
        return (ApprovalProcess.objects
                .filter(subject_type=self._subject_type(), subject_id=self.pk)
                .order_by("-created_at", "-id").first())

    @classmethod
    def _subject_type(cls) -> str:
        if not cls.SIGNOFF_SUBJECT_TYPE:
            raise ImproperlyConfiguredSubject(
                f"{cls.__name__} наследует Approvable, но не объявил "
                f"SIGNOFF_SUBJECT_TYPE"
            )
        return cls.SIGNOFF_SUBJECT_TYPE


# ═══════════════════════════════════════════════════════════════════════
# Маршрут — настройка
# ═══════════════════════════════════════════════════════════════════════

class ApprovalRoute(models.Model):
    """Маршрут согласования для одного типа объектов.

    Активный маршрут на тип — РОВНО один (частичный уникальный индекс ниже).
    Неактивные остаются в таблице как история: процессы, запущенные по
    старому маршруту, ссылаются на него ``route_id``, и удалять его значило
    бы стереть ответ на вопрос «по какому маршруту это согласовывали».
    """

    subject_type = models.CharField(max_length=64, db_index=True,
                                    verbose_name="Тип объекта")
    name = models.CharField(max_length=200, verbose_name="Название")
    is_active = models.BooleanField(default=True, db_default=True)
    created_at = models.DateTimeField(auto_now_add=True, db_default=Now())
    updated_at = models.DateTimeField(auto_now=True, db_default=Now())

    class Meta:
        ordering = ("subject_type", "-is_active", "name")
        constraints = [
            models.UniqueConstraint(
                fields=["subject_type"], condition=Q(is_active=True),
                name="uq_signoff_active_route_per_subject",
            ),
        ]
        verbose_name = "Маршрут согласования"
        verbose_name_plural = "Маршруты согласования"

    def __str__(self) -> str:
        return f"{self.name} ({self.subject_type})"


class ApprovalRouteStage(models.Model):
    """Этап маршрута.

    ``order`` — И порядок, И признак параллельности: этапы с одинаковым
    ``order`` идут одновременно, следующая группа получает запрос только
    когда предыдущая пройдена целиком. Поэтому уникальности по
    ``(route, order)`` здесь НЕТ — совпадение и есть механизм.

    ``name`` обязателен: согласующие заданы поимённо, и без названия этапа
    в карточке было бы видно только список фамилий, из которого непонятно,
    что именно эти люди проверяют.

    ``condition``/``is_fallback`` делают группу этапов ВЕТВЛЕНИЕМ: из группы
    с одинаковым ``order`` в процесс попадают только те этапы, чьё условие
    сошлось на фактах предметного объекта. Отдельной модели ветки нет
    намеренно — ветка и есть группа по ``order``, а условие лишь решает,
    кто из группы участвует. Подробности — ``services/conditions.py``.
    """

    route = models.ForeignKey(ApprovalRoute, on_delete=models.CASCADE,
                              related_name="stages")
    order = models.PositiveSmallIntegerField(
        default=1, db_default=1,
        verbose_name="Очередь",
        help_text="Одинаковая очередь = этапы идут параллельно",
    )
    name = models.CharField(max_length=200, verbose_name="Название этапа")
    quorum = models.CharField(max_length=8, choices=Quorum.choices,
                              default=Quorum.ALL, db_default=Quorum.ALL,
                              verbose_name="Кворум")
    # Список предикатов, соединённых И. Пустой список — «этап нужен всегда».
    # Формат и разбор — ``services/conditions.py``; здесь JSON, потому что
    # набор полей задаёт предметная аппка, а не signoff, и колонки под них
    # завести невозможно.
    condition = models.JSONField(
        default=list, blank=True, verbose_name="Условие",
        help_text="Пусто — этап нужен всегда",
    )
    # «Иначе» для своей группы: этап участвует, только если в группе не
    # сошлось ни одно условие. Отдельным флагом, а не условием `not_in`,
    # потому что список «всех прочих» пришлось бы дописывать вручную при
    # каждом новом значении справочника — а забытая дописка тихо выкинула
    # бы из согласования целый этап.
    is_fallback = models.BooleanField(
        default=False, db_default=False, verbose_name="Иначе",
        help_text="Этап для случая, когда в группе не сошлось ни одно условие",
    )

    class Meta:
        ordering = ("order", "id")
        verbose_name = "Этап маршрута"
        verbose_name_plural = "Этапы маршрута"

    def __str__(self) -> str:
        return f"{self.order}. {self.name}"

    def clean(self) -> None:
        """Проверка условия для django-admin.

        HTTP-путь проверяет условие в ``route_service._check_condition``, но
        админка сохраняет модель напрямую, мимо сервиса, — а поле у неё
        редактируется сырым JSON. Без этого в маршрут попадала бы опечатка,
        которая всплыла бы только на отправке заявки, у постороннего человека.

        Сервисы зовут ``save()``, а не ``full_clean()``, поэтому двойной
        проверки на HTTP-пути не возникает.
        """
        from django.core.exceptions import ValidationError

        from apps.signoff.services import conditions, registry

        if self.is_fallback and self.condition:
            raise ValidationError({
                "condition": "Этап «иначе» не может иметь собственного условия",
            })
        if not self.condition or not self.route_id:
            return
        try:
            conditions.validate(self.condition,
                                registry.fields_for(self.route.subject_type))
        except (conditions.ConditionError, registry.UnknownSubject) as exc:
            raise ValidationError({"condition": str(exc)}) from exc


class ApprovalRouteStageApprover(models.Model):
    """Согласующий на этапе маршрута.

    ``user_id`` — голый ``IntegerField``, не FK: ``apps.users`` — соседняя
    аппка, межаппный FK запрещён. Разрешение id в профиль — через
    ``apps.users.interface``.

    Ролей/групп здесь нет: платформа сознательно живёт без
    ``PermissionsMixin`` и Django-групп (см. ``apps/users/models.py``,
    решение Р1), а заводить третий параллельный ролевой механизм ради
    маршрутов согласования — плохой размен. Смысл этапа несёт его
    ``name``, а не роль исполнителя.
    """

    stage = models.ForeignKey(ApprovalRouteStage, on_delete=models.CASCADE,
                              related_name="approvers")
    user_id = models.IntegerField(db_index=True, verbose_name="Пользователь")

    class Meta:
        ordering = ("id",)
        constraints = [
            models.UniqueConstraint(fields=["stage", "user_id"],
                                    name="uq_signoff_stage_approver"),
        ]
        verbose_name = "Согласующий"
        verbose_name_plural = "Согласующие"

    def __str__(self) -> str:
        return f"user#{self.user_id} @ {self.stage_id}"


# ═══════════════════════════════════════════════════════════════════════
# Процесс — исполнение
# ═══════════════════════════════════════════════════════════════════════

class ApprovalProcess(models.Model):
    """Согласование одного объекта — живой экземпляр маршрута.

    ``subject_type``/``subject_id`` адресуют строку в чужой таблице. FK
    нет (межаппный запрещён), поэтому ссылочной целостности на уровне БД
    здесь тоже нет: удалённый предметный объект оставит висячий процесс.
    Это осознанный размен — предметные аппки удаляют такие строки
    единицами (в contracts удалить можно только черновик договора), а
    альтернатива — межаппный FK — ломает главный инвариант репозитория.

    ``route_id`` хранится голым числом СПРАВОЧНО: авторитетен снимок в
    ``ApprovalProcessStage``, а не текущее состояние маршрута.
    """

    subject_type = models.CharField(max_length=64, verbose_name="Тип объекта")
    subject_id = models.IntegerField(verbose_name="Объект")
    route_id = models.IntegerField(null=True, blank=True,
                                   verbose_name="Маршрут (справочно)")
    state = models.CharField(max_length=16, choices=ProcessState.choices,
                             default=ProcessState.PENDING,
                             db_default=ProcessState.PENDING, db_index=True)
    initiator_id = models.IntegerField(null=True, blank=True, db_index=True,
                                       verbose_name="Инициатор")
    # Какая группа этапов сейчас на рассмотрении. NULL — процесс завершён.
    current_order = models.PositiveSmallIntegerField(null=True, blank=True)
    # Факты предметного объекта на момент запуска — те, по которым выбирались
    # ветки (``services/conditions.py``). Хранятся, потому что через год
    # вопрос «почему этот бюджет ушёл именно этим людям» задаётся к процессу,
    # а предметный объект к тому времени уже отредактируют: без снимка
    # ответить на него нечем.
    subject_facts = models.JSONField(default=dict, blank=True,
                                     verbose_name="Факты объекта")
    created_at = models.DateTimeField(auto_now_add=True, db_default=Now())
    updated_at = models.DateTimeField(auto_now=True, db_default=Now())
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at", "-id")
        indexes = [
            models.Index(fields=["subject_type", "subject_id"],
                         name="ix_signoff_proc_subject"),
        ]
        constraints = [
            # Два одновременных согласования одного объекта — состояние, из
            # которого нет разумного выхода: какой из процессов решает
            # судьбу объекта? Повторная отправка возможна только после того,
            # как предыдущий процесс завершился.
            models.UniqueConstraint(
                fields=["subject_type", "subject_id"],
                condition=Q(state=ProcessState.PENDING),
                name="uq_signoff_one_pending_process_per_subject",
            ),
        ]
        verbose_name = "Процесс согласования"
        verbose_name_plural = "Процессы согласования"

    def __str__(self) -> str:
        return f"{self.subject_type}#{self.subject_id} — {self.get_state_display()}"


class ApprovalProcessStage(models.Model):
    """Этап живого процесса — СНИМОК этапа маршрута на момент запуска.

    Копия, а не FK на ``ApprovalRouteStage``, потому что маршрут — живая
    настройка: администратор вправе поменять его завтра, и правка не должна
    менять правила уже идущего согласования. Без снимка «кто должен был
    согласовать эту заявку» становится вопросом без ответа, стоит кому-то
    отредактировать маршрут — классический способ получить процесс,
    результат которого невозможно объяснить.

    Та же причина, по которой ``apps.approvals`` прикалывает
    ``template_version_id`` к своим заявкам; здесь снимок хранится строками,
    а не версией шаблона, потому что этапов единицы.
    """

    process = models.ForeignKey(ApprovalProcess, on_delete=models.CASCADE,
                                related_name="stages")
    order = models.PositiveSmallIntegerField()
    name = models.CharField(max_length=200)
    quorum = models.CharField(max_length=8, choices=Quorum.choices,
                              default=Quorum.ALL, db_default=Quorum.ALL)
    state = models.CharField(max_length=16, choices=StageState.choices,
                             default=StageState.WAITING,
                             db_default=StageState.WAITING)
    # Условие, по которому этап попал в процесс — часть того же снимка.
    # Пустое и у безусловных этапов, и у сработавшего «иначе» (у него
    # условия нет по определению), поэтому вместе с ним снимается
    # ``matched_by``: без него эти два случая в карточке неразличимы.
    condition = models.JSONField(default=list, blank=True)
    matched_by = models.CharField(max_length=16, default="always",
                                  db_default="always")
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("order", "id")
        indexes = [
            models.Index(fields=["process", "order"],
                         name="ix_signoff_stage_proc_order"),
        ]
        verbose_name = "Этап процесса"
        verbose_name_plural = "Этапы процесса"

    def __str__(self) -> str:
        return f"{self.order}. {self.name} — {self.get_state_display()}"


class ApprovalTask(models.Model):
    """Запрос решения к одному согласующему на одном этапе.

    Это же — индекс «ждёт моего решения»:
    ``ApprovalTask.objects.filter(user_id=me, state=PENDING,
    stage__state=ACTIVE)``, что и покрывает составной индекс ниже.
    """

    stage = models.ForeignKey(ApprovalProcessStage, on_delete=models.CASCADE,
                              related_name="tasks")
    user_id = models.IntegerField(verbose_name="Согласующий")
    state = models.CharField(max_length=16, choices=TaskState.choices,
                             default=TaskState.PENDING,
                             db_default=TaskState.PENDING)
    comment = models.TextField(default="", blank=True, db_default="")
    acted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_default=Now())

    class Meta:
        ordering = ("id",)
        constraints = [
            models.UniqueConstraint(fields=["stage", "user_id"],
                                    name="uq_signoff_task_stage_user"),
        ]
        indexes = [
            models.Index(fields=["user_id", "state"],
                         name="ix_signoff_task_user_state"),
        ]
        verbose_name = "Запрос на согласование"
        verbose_name_plural = "Запросы на согласование"

    def __str__(self) -> str:
        return f"user#{self.user_id}: {self.get_state_display()}"


class ApprovalEvent(models.Model):
    """Журнал процесса — append-only.

    Отдельно от ``ApprovalTask``, хотя решения видны и там: задача хранит
    ПОСЛЕДНЕЕ состояние, а журнал — последовательность. «Почему заявка
    отклонена» и «в каком порядке это происходило» — вопросы к журналу.
    """

    process = models.ForeignKey(ApprovalProcess, on_delete=models.CASCADE,
                                related_name="events")
    kind = models.CharField(max_length=32)
    actor_id = models.IntegerField(null=True, blank=True)
    payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_default=Now())

    class Meta:
        ordering = ("id",)
        verbose_name = "Событие согласования"
        verbose_name_plural = "Журнал согласования"

    def __str__(self) -> str:
        return f"{self.kind} @ process#{self.process_id}"
