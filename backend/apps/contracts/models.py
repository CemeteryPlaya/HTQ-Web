"""Модели домена contracts — «Бюджет / Реестр контрактов / Договор».

Реализован вариант B («Бюджетная строка») из обсуждения проектирования:
деньги лежат на бюджетной СТРОКЕ (связка администратор × программа × год),
а не на человеке-администраторе. Администратор — запись справочника без
собственной суммы; у одного администратора может быть несколько бюджетов
под разные программы, с раздельными лимитами.

Три слоя:

1. Справочники бюджета — ``Country``, ``Program``, ``Administrator``,
   ``Budget``. Меняются редко, ведутся финансистами.
2. Реестр контрагентов — ``Counterparty``. Карточка организации/ИП, с
   которой заключается договор. В исходной спецификации заказчика таблица
   называется «Реестр контрактов», но её поля (БИН/ИИН, НДС, адрес) — это
   атрибуты КОНТРАГЕНТА, а не договора, поэтому модель названа по существу.
3. ``Agreement`` — единственная транзакционная сущность, всё остальное
   справочники.

Остаток бюджета НИГДЕ не хранится: он вычисляется в
``services/budget_calc.py`` как ``amount − SUM(договоры в учитываемых
статусах)``. Хранимый остаток, который уменьшают операцией ``-=``, ломается
при редактировании суммы договора, его удалении, расторжении или сбое
записи — и после этого невозможно определить, какая цифра верна. Поэтому
поля ``committed``/``remaining`` на ``Budget`` НЕТ и появиться не должно.

Все внешние ключи — ``PROTECT``: справочник, на который ссылается живой
бюджет или договор, удалить нельзя. Вывод из оборота — через
``is_active=False`` / ``status``.
"""

from django.db import models
from django.db.models.functions import Now


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
        return f"{self.name} / {self.expense_item}"


class Administrator(models.Model):
    """Администратор бюджета — физическое лицо, держатель бюджетных строк.

    Денег на этой записи НЕТ: суммы лежат на ``Budget``. Это и есть отличие
    варианта B от «плоского» варианта A, где сумма была бы здесь.

    ``user_id`` — необязательная ссылка на учётную запись платформы. Хранится
    голым ``IntegerField``, а не FK: ``apps.users`` — соседняя аппка, и
    междоменный FK запрещён (см. ``apps/core/tests/test_app_isolation.py``).
    Разрешение id в профиль — только через ``apps.users.interface``.
    Заполнять необязательно; сейчас никто в платформе не логинится «как
    администратор бюджета».
    """

    full_name = models.CharField(max_length=200)
    country = models.ForeignKey(Country, on_delete=models.PROTECT,
                                related_name="administrators")
    project_name = models.CharField(max_length=200)
    user_id = models.IntegerField(null=True, blank=True, db_index=True)
    is_active = models.BooleanField(default=True, db_default=True)
    created_at = models.DateTimeField(auto_now_add=True, db_default=Now())
    updated_at = models.DateTimeField(auto_now=True, db_default=Now())

    class Meta:
        ordering = ("full_name",)
        verbose_name = "Администратор бюджета"
        verbose_name_plural = "Администраторы бюджета"

    def __str__(self) -> str:
        return f"{self.full_name} ({self.project_name})"


class Budget(models.Model):
    """Бюджетная строка — выделенная сумма на связку (администратор × программа × год).

    ``amount`` — сколько выделено. Сколько законтрактовано и сколько осталось,
    здесь НЕ хранится (см. докстринг модуля); эти числа считает
    ``services.budget_calc``.
    """

    administrator = models.ForeignKey(Administrator, on_delete=models.PROTECT,
                                      related_name="budgets")
    program = models.ForeignKey(Program, on_delete=models.PROTECT,
                                related_name="budgets")
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    currency = models.CharField(max_length=3, default="KZT", db_default="KZT")
    period_year = models.IntegerField()
    status = models.CharField(max_length=16, choices=BudgetStatus.choices,
                              default=BudgetStatus.ACTIVE,
                              db_default=BudgetStatus.ACTIVE)
    note = models.TextField(default="", blank=True, db_default="")
    created_at = models.DateTimeField(auto_now_add=True, db_default=Now())
    updated_at = models.DateTimeField(auto_now=True, db_default=Now())

    class Meta:
        ordering = ("-period_year", "administrator_id", "program_id")
        constraints = [
            # Одна бюджетная строка на связку — иначе «остаток по программе»
            # перестаёт быть однозначным числом.
            models.UniqueConstraint(fields=["administrator", "program", "period_year"],
                                    name="uq_contracts_budget_admin_program_year"),
        ]
        verbose_name = "Бюджет"
        verbose_name_plural = "Бюджеты"

    def __str__(self) -> str:
        return f"{self.administrator_id}/{self.program_id} {self.period_year}: {self.amount} {self.currency}"


class Counterparty(models.Model):
    """Контрагент — «Реестр контрактов» в терминах заказчика.

    ``vat`` и ``contacts`` намеренно оставлены свободным текстом: заказчик
    пока не уточнил, значит ли «НДС» признак плательщика (булево + номер
    свидетельства) или ставку, а «Контакты» — одну строку или список
    контактных лиц. Разворачивать текстовое поле в структуру дешевле, чем
    угадать структуру неверно и потом её ломать.
    """

    # 12 у казахстанского БИН/ИИН, но справочник стран общий и иностранный
    # контрагент приходит с номером другой формы — поле шире номинала
    # намеренно (см. схему CounterpartyCreate).
    bin_iin = models.CharField(max_length=32, unique=True)
    name = models.CharField(max_length=300)
    vat = models.CharField(max_length=100, default="", blank=True, db_default="")
    contacts = models.TextField(default="", blank=True, db_default="")
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
        verbose_name_plural = "Реестр контрактов"

    def __str__(self) -> str:
        return f"{self.name} ({self.bin_iin})"


class Agreement(models.Model):
    """Договор — единственная транзакционная сущность модуля.

    Ссылается на ОДНУ бюджетную строку. В интерфейсе пользователь выбирает
    администратора, затем программу (каскадные списки, как в спецификации),
    но на бэкенд приходит один ``budget_id``: хранить отдельно
    ``administrator``/``program`` рядом с ``budget`` значило бы завести две
    версии правды о том, из какого кармана взяты деньги.

    ``file_id`` — идентификатор ``FileMetadata`` в ``apps.media_files``,
    полученный через ``apps.media_files.interface.store_file()``. Свой бакет
    модуль не заводит (инвариант №10, backend/README.md). Хранится строкой,
    а не FK: междоменный FK запрещён.

    Первая фаза — один файл на договор. Дополнительные соглашения и акты
    потребуют дочерней таблицы ``AgreementFile``; это осознанно отложено.
    """

    number = models.CharField(max_length=100, unique=True)
    name = models.CharField(max_length=300)
    budget = models.ForeignKey(Budget, on_delete=models.PROTECT,
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
            # Профиль запросов модуля: «договоры этой бюджетной строки в
            # учитываемых статусах» — то, что budget_calc агрегирует на
            # каждом чтении бюджета.
            models.Index(fields=["budget", "status"], name="ix_contracts_agr_budget_st"),
        ]
        verbose_name = "Договор"
        verbose_name_plural = "Договоры"

    def __str__(self) -> str:
        return f"{self.number} — {self.name}"
