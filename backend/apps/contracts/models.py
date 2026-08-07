"""Модели домена contracts — «Бюджет / Реестр контрагентов / Договор».

Развитие варианта B («Бюджетная строка») из обсуждения проектирования:
деньги лежат на бюджетной СТРОКЕ, а не на человеке-администраторе.
Администратор — запись справочника без собственной суммы.

Строки при этом собраны в КОНТЕЙНЕР: ``Budget`` — это бюджет проекта на год
целиком (администратор × год × валюта), а ``BudgetLine`` — сумма, выделенная
внутри него одной программе. Изначально контейнера не было и «бюджетом»
звалась сама строка; его завели, когда выяснилось, что заказчик заводит и
согласует бюджет проекта списком программ целиком, а не программу за
программой. Деньги остались на строке — договор ссылается на неё, — но
согласование и итог принадлежат контейнеру.

Три слоя:

1. Справочники бюджета — ``Country``, ``Program``, ``Administrator``.
   Меняются редко, ведутся финансистами. Рядом — ``Budget``/``BudgetLine``:
   уже не справочник, но и не транзакционная запись.
2. Реестр контрагентов — ``Counterparty``. Карточка организации/ИП, с
   которой заключается договор. В исходной спецификации заказчика таблица
   называлась «Реестр контрактов», но её поля (БИН/ИИН, НДС, адрес) — это
   атрибуты КОНТРАГЕНТА, а не договора, поэтому и модель, и подпись в UI
   названы по существу — «Реестр контрагентов».
3. ``Agreement`` — единственная транзакционная сущность, всё остальное
   справочники.

Остаток бюджета НИГДЕ не хранится: он вычисляется в
``services/budget_calc.py`` как ``line.amount − SUM(договоры строки в
учитываемых статусах)``, а по бюджету целиком — суммированием строк.
Хранимый остаток, который уменьшают операцией ``-=``, ломается при
редактировании суммы договора, его удалении, расторжении или сбое записи —
и после этого невозможно определить, какая цифра верна. Поэтому полей
``committed``/``remaining`` нет ни на ``BudgetLine``, ни на ``Budget``, и
появиться они не должны; по той же причине на ``Budget`` нет и хранимого
``amount`` — «выделено» это сумма строк.

Все внешние ключи — ``PROTECT``: справочник, на который ссылается живой
бюджет или договор, удалить нельзя. Вывод из оборота — через
``is_active=False`` / ``status``.

Согласование. ``Budget``, ``Counterparty`` и ``Agreement`` наследуют примесь
``signoff.Approvable``: она добавляет в ИХ ЖЕ таблицы колонку
``approval_state`` и связывает запись с движком ``apps.signoff`` через пару
``(SIGNOFF_SUBJECT_TYPE, pk)``. Межаппного FK при этом не возникает —
signoff адресует чужие строки строкой типа и числом, а не ключом
(см. докстринг ``apps/signoff/models.py``). Импорт идёт через
``apps.signoff.interface`` — единственную форму, разрешённую
``apps/core/tests/test_app_isolation.py``.

``status`` и ``approval_state`` — РАЗНЫЕ оси и обе остаются. ``status`` —
жизненный цикл записи в предметной области («бюджет закрыт», «контрагент
заблокирован», «договор расторгнут»); ``approval_state`` — где запись
находится в согласовании. Договор может быть одновременно «согласован» по
маршруту и «расторгнут» по существу. Единственное место, где оси связаны, —
``approval_hooks``: у договора результат согласования двигает его
``status`` по ``ALLOWED_TRANSITIONS``.
"""

from django.db import models
from django.db.models.functions import Now

# Сосед — только через interface (apps/core/tests/test_app_isolation.py).
# Из signoff здесь берётся ровно один класс — абстрактная примесь.
from apps.signoff import interface as signoff


class BudgetStatus(models.TextChoices):
    ACTIVE = "active", "Активен"
    CLOSED = "closed", "Закрыт"


class CounterpartyStatus(models.TextChoices):
    # ⚠️ Открытый вопрос к заказчику: поле статуса контрагента может означать
    # либо жизненный цикл записи (черновик/активен/архив), либо результат
    # проверки (проверен / в чёрном списке). Это две разные оси, и их часто
    # смешивают в одном поле. Здесь принята первая трактовка; если окажется
    # верной вторая — добавляется отдельное поле, а не переопределяется это.
    ACTIVE = "active", "Активен"
    INACTIVE = "inactive", "Неактивен"
    BLOCKED = "blocked", "Заблокирован"


class PaymentType(models.TextChoices):
    PREPAYMENT = "prepayment", "Предоплата"
    POSTPAYMENT = "postpayment", "Постоплата"
    STAGED = "staged", "Поэтапно"


class AgreementStatus(models.TextChoices):
    DRAFT = "draft", "Черновик"
    ON_REVIEW = "on_review", "На согласовании"
    APPROVED = "approved", "Согласован"
    SIGNED = "signed", "Подписан"
    EXECUTED = "executed", "Исполнен"
    TERMINATED = "terminated", "Расторгнут"


class InvoiceStatus(models.TextChoices):
    # У счёта нет «подписан»: договор подписывают две стороны, счёт же просто
    # оплачивают. Поэтому вместо ``signed → executed`` здесь один терминальный
    # ``paid``. ``cancelled`` — второй терминал, аналог ``terminated`` у
    # договора: счёт отозвали, не оплатив.
    DRAFT = "draft", "Черновик"
    ON_REVIEW = "on_review", "На согласовании"
    APPROVED = "approved", "Согласован"
    PAID = "paid", "Оплачен"
    CANCELLED = "cancelled", "Отменён"


class AdvancePaymentStatus(models.TextChoices):
    """Доменная стадия предоплаты, отдельная от решения signoff."""

    DRAFT = "draft", "Черновик"
    ON_REVIEW = "on_review", "На согласовании"
    AWAITING_ACCOUNTING = "awaiting_accounting", "Ожидает оформления бухгалтерией"
    CLOSED = "closed", "Закрыт"


class Country(models.Model):
    """Страна. Используется и администратором бюджета, и контрагентом."""

    name = models.CharField(max_length=100, unique=True)
    iso_code = models.CharField(max_length=3, default="", blank=True, db_default="")
    created_at = models.DateTimeField(auto_now_add=True, db_default=Now())

    class Meta:
        ordering = ("name",)
        verbose_name = "Страна"
        verbose_name_plural = "Страны"

    def __str__(self) -> str:
        return self.name


class Program(models.Model):
    """Программа + статья расходов.

    Держатся в одной таблице — ровно как в спецификации заказчика. Если
    позже понадобится «одна программа → несколько статей расходов»,
    ``expense_item`` выносится в отдельную модель ``ExpenseItem`` с FK на
    ``Program``; миграция несложная, потому что ``Budget`` ссылается на
    программу одним ключом и это единственное место, которое придётся
    переподключить.
    """

    name = models.CharField(max_length=200)
    expense_item = models.CharField(max_length=200)
    code = models.CharField(max_length=50, default="", blank=True, db_default="")
    is_active = models.BooleanField(default=True, db_default=True)
    created_at = models.DateTimeField(auto_now_add=True, db_default=Now())
    updated_at = models.DateTimeField(auto_now=True, db_default=Now())

    class Meta:
        ordering = ("name", "expense_item")
        constraints = [
            models.UniqueConstraint(fields=["name", "expense_item"],
                                    name="uq_contracts_program_name_item"),
        ]
        verbose_name = "Программа"
        verbose_name_plural = "Программы"

    def __str__(self) -> str:
        return self.display_name

    # Подпись программы — «код название». Собирается здесь и берётся отсюда
    # всеми, кто её показывает (``ProgramRead.display_name``, django-admin),
    # тем же приёмом, что и у ``Administrator.display_name``.
    #
    # ``code`` необязателен, поэтому склейка идёт по непустым частям: у
    # программы без кода подпись — просто название, а не пробел и название.
    # Статьи расходов в подписи НЕТ намеренно: она не различает программы в
    # выпадающем списке настолько, чтобы удлинять на неё каждую строку, и
    # показывается отдельным полем/подсказкой.
    @property
    def display_name(self) -> str:
        return " ".join(part for part in (self.code, self.name) if part)


class Administrator(models.Model):
    """Администратор бюджета — держатель бюджетных строк.

    Денег на этой записи НЕТ: суммы лежат на ``Budget``. Это и есть отличие
    варианта B от «плоского» варианта A, где сумма была бы здесь.

    Запись опознаётся ПРОЕКТОМ и СТРАНОЙ, а не именем человека: ФИО здесь
    было, но заказчик его снял — бюджет ведётся по проекту, а кто именно им
    занимается, меняется чаще, чем сам проект, и в бюджетной строке этого
    знать не нужно. Кто отвечает за запись в платформе, при необходимости
    говорит ``user_id``.

    ``user_id`` — необязательная ссылка на учётную запись платформы. Хранится
    голым ``IntegerField``, а не FK: ``apps.users`` — соседняя аппка, и
    междоменный FK запрещён (см. ``apps/core/tests/test_app_isolation.py``).
    Разрешение id в профиль — только через ``apps.users.interface``.
    Заполнять необязательно; сейчас никто в платформе не логинится «как
    администратор бюджета».
    """

    country = models.ForeignKey(Country, on_delete=models.PROTECT,
                                related_name="administrators")
    project_name = models.CharField(max_length=200)
    user_id = models.IntegerField(null=True, blank=True, db_index=True)
    is_active = models.BooleanField(default=True, db_default=True)
    created_at = models.DateTimeField(auto_now_add=True, db_default=Now())
    updated_at = models.DateTimeField(auto_now=True, db_default=Now())

    class Meta:
        ordering = ("project_name",)
        verbose_name = "Администратор бюджета"
        verbose_name_plural = "Администраторы бюджета"

    def __str__(self) -> str:
        return f"{self.project_name} {self.country.name}"

    # Читаемое имя записи собирается ЗДЕСЬ и берётся отсюда всеми, кто его
    # показывает (``AdministratorRead.display_name``, ``administrator_name``
    # в карточках бюджета и договора, заголовки signoff). Иначе формат
    # «проект + страна» пришлось бы повторить в пяти местах и он разъехался
    # бы при первой же правке.
    @property
    def display_name(self) -> str:
        return str(self)

    @property
    def country_name(self) -> str:
        return self.country.name


class Budget(signoff.Approvable, models.Model):
    """Бюджет проекта на год — КОНТЕЙНЕР строк, а не сама сумма.

    Денег на этой записи нет ни одной колонкой: «выделено» — это сумма
    ``BudgetLine.amount`` его строк, и считает её ``budget_calc``, как и
    «законтрактовано» с «остатком». Хранимый итог пришлось бы поддерживать
    при каждой правке строки, и он разъезжался бы ровно так же, как
    разъезжается хранимый остаток (см. докстринг модуля).

    Почему контейнер, а не плоская строка на программу (как было до этого):
    заказчик заводит бюджет проекта на год ЦЕЛИКОМ — списком программ с
    суммами и общим итогом — и согласует его тоже целиком. При плоской
    модели «заявка» существовала только в форме ввода: после отправки она
    распадалась на независимые записи, которые подписывающий вынужден был
    утверждать по одной, имея возможность пропустить часть.

    Отсюда и то, что согласуется ИМЕННО эта модель (``Approvable`` здесь, а
    не на ``BudgetLine``): согласовать половину бюджета нельзя.

    ``currency`` общая на все строки: разные валюты в одном контейнере
    лишили бы его итог смысла — сложить их было бы нечем. Проекту, которому
    нужен бюджет в другой валюте, заводится отдельный ``Budget`` за тот же
    год, поэтому валюта входит в ключ уникальности.
    """

    SIGNOFF_SUBJECT_TYPE = "contracts.budget"

    administrator = models.ForeignKey(Administrator, on_delete=models.PROTECT,
                                      related_name="budgets")
    period_year = models.IntegerField()
    currency = models.CharField(max_length=3, default="KZT", db_default="KZT")
    status = models.CharField(max_length=16, choices=BudgetStatus.choices,
                              default=BudgetStatus.ACTIVE,
                              db_default=BudgetStatus.ACTIVE)
    note = models.TextField(default="", blank=True, db_default="")
    created_at = models.DateTimeField(auto_now_add=True, db_default=Now())
    updated_at = models.DateTimeField(auto_now=True, db_default=Now())

    class Meta:
        ordering = ("-period_year", "administrator_id")
        constraints = [
            # Один бюджет на связку «проект × год × валюта». Иначе тот же
            # проект за тот же год получил бы два контейнера, и вопрос
            # «сколько выделено проекту на 2026-й» перестал бы иметь один
            # ответ.
            models.UniqueConstraint(fields=["administrator", "period_year", "currency"],
                                    name="uq_contracts_budget_admin_year_currency"),
        ]
        verbose_name = "Бюджет"
        verbose_name_plural = "Бюджеты"

    def __str__(self) -> str:
        return f"Бюджет {self.period_year}: {self.administrator_id} ({self.currency})"


class BudgetLine(models.Model):
    """Строка бюджета — сумма, выделенная одной программе.

    Это то, на что ссылается договор и по чему считается остаток: деньги
    расходуются по программам, а не по бюджету целиком. Поэтому
    ``Agreement`` смотрит СЮДА, а не на ``Budget``.

    Собственного согласования у строки нет (``Approvable`` — на ``Budget``):
    строка согласована ровно тогда, когда согласован её бюджет. Дублировать
    состояние на строке значило бы завести вторую версию правды о том, можно
    ли с неё тратить.

    ``on_delete=CASCADE`` к бюджету: строка без бюджета не имеет смысла.
    Удаление бюджета со строками, к которым привязаны договоры, при этом всё
    равно не пройдёт — договор держит строку через ``PROTECT``, и Django
    отдаст ``ProtectedError`` на сборе каскада.
    """

    budget = models.ForeignKey(Budget, on_delete=models.CASCADE,
                               related_name="lines")
    program = models.ForeignKey(Program, on_delete=models.PROTECT,
                                related_name="budget_lines")
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    note = models.TextField(default="", blank=True, db_default="")
    created_at = models.DateTimeField(auto_now_add=True, db_default=Now())
    updated_at = models.DateTimeField(auto_now=True, db_default=Now())

    class Meta:
        ordering = ("budget_id", "program_id")
        constraints = [
            # Одна строка на программу внутри бюджета — иначе «остаток по
            # программе» перестаёт быть однозначным числом. Вместе с
            # уникальностью самого бюджета это даёт прежний инвариант
            # «администратор × программа × год».
            models.UniqueConstraint(fields=["budget", "program"],
                                    name="uq_contracts_budgetline_budget_program"),
        ]
        verbose_name = "Строка бюджета"
        verbose_name_plural = "Строки бюджета"

    def __str__(self) -> str:
        return f"{self.program_id}: {self.amount}"

    # Год, валюта и администратор у строки СВОИХ колонок не имеют — они
    # принадлежат бюджету. Проксирующие свойства нужны, чтобы сериализация
    # строки («плоская» карточка для формы договора) не собирала их вручную
    # в трёх местах. Читающие пути обязаны тянуть `budget__administrator`,
    # иначе это N+1.
    @property
    def period_year(self) -> int:
        return self.budget.period_year

    @property
    def currency(self) -> str:
        return self.budget.currency


class Counterparty(signoff.Approvable, models.Model):
    """Контрагент — раздел «Реестр контрагентов».

    ``vat`` — ПРИЗНАК плательщика НДС, «с НДС / без НДС». Поле было
    свободным текстом, пока заказчик не уточнил, что за ним стоит: ни
    ставки, ни номера свидетельства здесь не ведётся. Понадобится номер —
    это отдельное поле рядом (``vat_certificate``), а не возврат булева
    признака в строку: два разных факта в одной колонке — то, из-за чего
    поле и переписывалось.

    Контакты — три отдельных поля (``contact_name``, ``phone``, ``email``),
    а не бывшая свободная строка ``contacts``: из неё нельзя было ни взять
    адрес для письма, ни проверить, что e-mail вообще похож на e-mail, ни
    показать телефон отдельной колонкой.

    ``contact_name`` подписан «Генеральный директор»: должность задана самой
    подписью поля, отдельной колонки под должность НЕТ — иначе ею пришлось бы
    заниматься при каждой кадровой перестановке у контрагента. Понадобится
    контакт с другой должностью — это дочерняя таблица
    ``CounterpartyContact``, а не «должность» рядом с ``contact_name`` и не
    возврат к свободной строке.
    """

    SIGNOFF_SUBJECT_TYPE = "contracts.counterparty"

    # 12 у казахстанского БИН/ИИН, но справочник стран общий и иностранный
    # контрагент приходит с номером другой формы — поле шире номинала
    # намеренно (см. схему CounterpartyCreate).
    bin_iin = models.CharField(max_length=32, unique=True)
    name = models.CharField(max_length=300)
    vat = models.BooleanField(default=False, db_default=False,
                              verbose_name="Плательщик НДС")
    contact_name = models.CharField(max_length=200, blank=True, default="",
                                    db_default="",
                                    verbose_name="Генеральный директор")
    phone = models.CharField(max_length=30, blank=True, default="",
                             db_default="", verbose_name="Телефон")
    email = models.EmailField(max_length=254, blank=True, default="",
                              db_default="", verbose_name="E-mail")
    address = models.TextField(default="", blank=True, db_default="")
    country = models.ForeignKey(Country, on_delete=models.PROTECT,
                                related_name="counterparties")
    status = models.CharField(max_length=16, choices=CounterpartyStatus.choices,
                              default=CounterpartyStatus.ACTIVE,
                              db_default=CounterpartyStatus.ACTIVE)
    created_at = models.DateTimeField(auto_now_add=True, db_default=Now())
    updated_at = models.DateTimeField(auto_now=True, db_default=Now())

    class Meta:
        ordering = ("name",)
        indexes = [models.Index(fields=["name"], name="ix_contracts_cp_name")]
        verbose_name = "Контрагент"
        verbose_name_plural = "Реестр контрагентов"

    def __str__(self) -> str:
        return f"{self.name} ({self.bin_iin}, {self.vat_label})"

    # «с НДС» / «без НДС». Подпись живёт на модели, а не в шаблоне и не
    # во фронтенде: её показывают и __str__ (django-admin, заголовки
    # signoff), и карточка контрагента в API — один булев признак не
    # должен получить два разных словесных перевода.
    @property
    def vat_label(self) -> str:
        return "с НДС" if self.vat else "без НДС"

    # Однострочная склейка контактов — для списков и заголовков, где место
    # есть только под одну строку. Живёт на модели по той же причине, что и
    # vat_label: иначе порядок и разделители разойдутся между реестром,
    # карточкой и django-admin. Хранимого поля за ней нет — только три
    # колонки выше.
    @property
    def contact_summary(self) -> str:
        parts = [self.contact_name, self.phone, self.email]
        return ", ".join(part for part in parts if part)


class Agreement(signoff.Approvable, models.Model):
    """Договор — единственная транзакционная сущность модуля.

    Ссылается на ОДНУ строку бюджета (``BudgetLine``), а не на бюджет
    целиком: деньги выделены программе, и списываться должны с неё. В
    интерфейсе пользователь выбирает администратора, затем программу
    (каскадные списки, как в спецификации), но на бэкенд приходит один
    ``budget_line_id``: хранить отдельно ``administrator``/``program`` рядом
    со ссылкой значило бы завести две версии правды о том, из какого кармана
    взяты деньги.

    ``file_id`` — идентификатор ``FileMetadata`` в ``apps.media_files``,
    полученный через ``apps.media_files.interface.store_file()``. Свой бакет
    модуль не заводит (инвариант №10, backend/README.md). Хранится строкой,
    а не FK: междоменный FK запрещён.

    Первая фаза — один файл на договор. Дополнительные соглашения и акты
    потребуют дочерней таблицы ``AgreementFile``; это осознанно отложено.

    Единственная из трёх согласуемых моделей, у которой результат
    согласования имеет ДОМЕННОЕ последствие: он двигает ``status`` по
    ``ALLOWED_TRANSITIONS`` (``draft`` → ``on_review`` → ``approved``, отказ
    возвращает в ``draft``). Делает это ``approval_hooks``, а не сам движок:
    таблица переходов — дело этой аппки.
    """

    SIGNOFF_SUBJECT_TYPE = "contracts.agreement"

    number = models.CharField(max_length=100, unique=True)
    name = models.CharField(max_length=300)
    budget_line = models.ForeignKey(BudgetLine, on_delete=models.PROTECT,
                                    related_name="agreements")
    counterparty = models.ForeignKey(Counterparty, on_delete=models.PROTECT,
                                     related_name="agreements")
    payment_type = models.CharField(max_length=20, choices=PaymentType.choices,
                                    default=PaymentType.POSTPAYMENT,
                                    db_default=PaymentType.POSTPAYMENT)
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    currency = models.CharField(max_length=3, default="KZT", db_default="KZT")
    file_id = models.CharField(max_length=64, null=True, blank=True)
    signed_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=AgreementStatus.choices,
                              default=AgreementStatus.DRAFT,
                              db_default=AgreementStatus.DRAFT)
    created_by = models.IntegerField(null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_default=Now())
    updated_at = models.DateTimeField(auto_now=True, db_default=Now())

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            # Профиль запросов модуля: «договоры этой строки бюджета в
            # учитываемых статусах» — то, что budget_calc агрегирует на
            # каждом чтении бюджета.
            models.Index(fields=["budget_line", "status"],
                         name="ix_contracts_agr_line_st"),
        ]
        verbose_name = "Договор"
        verbose_name_plural = "Договоры"

    def __str__(self) -> str:
        return f"{self.number} — {self.name}"


class Invoice(signoff.Approvable, models.Model):
    """Счёт на оплату БЕЗ договора — прямая закупка, за которой не стоит
    ``Agreement``.

    Это второй, помимо договора, канал расхода бюджета: покупку оформляют
    одним счётом, без заключения договора. Поэтому по устройству счёт —
    брат ``Agreement``: та же ссылка на ОДНУ строку бюджета (деньги выделены
    программе), тот же контрагент-поставщик, та же приложенная к записи
    сумма и скан.

    Отличий от договора три, и все намеренные:

    1. **Номера нет.** У договора ``number`` — уникальный ключ, по которому
       на него ссылаются. Счёт без договора так не адресуют: он опознаётся
       наименованием закупки и поставщиком. Номер поставщика, если понадобится
       его хранить, — отдельное необязательное поле рядом, а не возврат к
       уникальному ключу, которого у этой записи по смыслу нет.

    2. **Валюта не приходит из формы — она снимается со строки бюджета**
       (``budget_line.budget.currency``) при создании. У договора валюта в
       теле запроса и сверяется с бюджетом; здесь сверять нечего — счёт
       выписывается в валюте того бюджета, из которого его оплачивают, и
       принимать её отдельным полем значило бы завести возможность
       рассогласования на ровном месте. Колонка всё же есть (снимок на момент
       создания), чтобы карточка и списки не лезли за валютой в бюджет.

    3. **Счёт занимает бюджет после согласования.** ``budget_calc`` включает
       в остаток счета в статусах ``approved`` и ``paid``. При создании сумма
       уже проверяется относительно остатка, а при одобрении проверяется
       повторно под блокировкой строки: черновик и счёт на согласовании не
       резервируют деньги, но согласовать сверх доступной суммы нельзя.

    ``file_id`` — «Скан счёта на оплату» в ``apps.media_files``, тем же
    путём ``interface.store_file()``, что и скан договора (свой бакет модуль
    не заводит — инвариант №10, backend/README.md).

    ``Approvable`` подмешан сразу, хотя маршрут согласования счёта в первой
    фазе не подключён: колонка ``approval_state`` появляется в таблице сейчас
    (иначе её ввод потребовал бы отдельной миграции), а её ведёт signoff,
    когда счёт зарегистрируют согласуемым типом. До тех пор она инертна
    (``draft``), маршрута нет, гейт молчит. ``status`` и ``approval_state`` —
    те же две разные оси, что и у договора (см. докстринг модуля).
    """

    SIGNOFF_SUBJECT_TYPE = "contracts.invoice"

    name = models.CharField(max_length=300, verbose_name="Наименование")
    note = models.TextField(default="", blank=True, db_default="",
                            verbose_name="Пояснение")
    budget_line = models.ForeignKey(BudgetLine, on_delete=models.PROTECT,
                                    related_name="invoices")
    counterparty = models.ForeignKey(Counterparty, on_delete=models.PROTECT,
                                     related_name="invoices")
    amount = models.DecimalField(max_digits=18, decimal_places=2,
                                 verbose_name="Сумма счёта")
    currency = models.CharField(max_length=3, default="KZT", db_default="KZT")
    file_id = models.CharField(max_length=64, null=True, blank=True,
                               verbose_name="Скан счёта на оплату")
    status = models.CharField(max_length=20, choices=InvoiceStatus.choices,
                              default=InvoiceStatus.DRAFT,
                              db_default=InvoiceStatus.DRAFT)
    created_by = models.IntegerField(null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_default=Now())
    updated_at = models.DateTimeField(auto_now=True, db_default=Now())

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            # Тот же профиль, что у договора: «счета этой строки бюджета в
            # таком-то статусе» — то, что понадобится, когда счета начнут
            # учитываться в остатке (см. докстринг, пункт 3).
            models.Index(fields=["budget_line", "status"],
                         name="ix_contracts_inv_line_st"),
        ]
        verbose_name = "Счёт на оплату"
        verbose_name_plural = "Счета на оплату"

    def __str__(self) -> str:
        return f"Счёт: {self.name} ({self.amount} {self.currency})"


class AdvancePayment(signoff.Approvable, models.Model):
    """Предоплата, запрашиваемая на основании уже согласованного договора.

    Согласование самой предоплаты и её фактическое проведение разделены.
    ``approval_state`` ведёт signoff, а ``status`` — собственный жизненный
    цикл документа. После положительного решения статус становится
    ``awaiting_accounting``; файл платёжного поручения и номер проводки
    появляются только отдельным действием бухгалтера, которое закрывает
    документ. Это не ещё один этап согласования: бухгалтер фиксирует
    исполнение платежа, а не принимает решение по нему.
    """

    SIGNOFF_SUBJECT_TYPE = "contracts.advance_payment"

    agreement = models.ForeignKey(Agreement, on_delete=models.PROTECT,
                                  related_name="advance_payments")
    amount = models.DecimalField(max_digits=18, decimal_places=2,
                                 verbose_name="Сумма предоплаты")
    status = models.CharField(max_length=24, choices=AdvancePaymentStatus.choices,
                              default=AdvancePaymentStatus.DRAFT,
                              db_default=AdvancePaymentStatus.DRAFT)
    payment_order_file_id = models.CharField(
        max_length=64, null=True, blank=True,
        verbose_name="Файл платёжного поручения",
    )
    posting_number = models.CharField(max_length=100, default="", blank=True,
                                      db_default="", verbose_name="Номер проводки")
    paid_by = models.IntegerField(null=True, blank=True, db_index=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    created_by = models.IntegerField(null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_default=Now())
    updated_at = models.DateTimeField(auto_now=True, db_default=Now())

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["agreement", "approval_state"],
                         name="ix_ctr_adv_agr_state"),
        ]
        verbose_name = "Предоплата на основании договора"
        verbose_name_plural = "Предоплаты на основании договоров"

    def __str__(self) -> str:
        return f"Предоплата по договору {self.agreement.number}: {self.amount}"
