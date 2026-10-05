"""Счета организации и шаблоны выписок (ТЗ §11.2, §18 — строка «Банковские
счета организации и шаблоны выписок», задача A3.1) и загрузки выписок со
строками (ТЗ §11.2–11.3, §15.5, A4.1 — ниже, после счетов).

Справочник ведёт АДМ (узел ``bpp.settings``), читают ФД и БУХ (``bpp.bank``).
Удаления нет — архив ``is_active=False`` (ТЗ §18: «Да / да / архив»).

**Шаблон выписки** описывает, как читать файл банк-клиента. Код не знает ни
одного банка (D-S3-3): Excel и CSV разбираются только по шаблону.
``columns`` — «поле выписки → текст заголовка колонки в файле»; колонки
ищутся по заголовку, а не по номеру, поэтому их порядок в файле не важен
(``services/bank/templates.py``). Выписке 1С (1CClientBankExchange) колонки
не нужны: имена полей задаёт стандарт формата, разбор — задача 3.

``amount_mode``: ``signed`` — одна колонка суммы со знаком, отрицательная
сумма — списание (дебет), положительная — поступление; ``split`` — две
колонки «Дебет» и «Кредит», списание — непустой дебет.

``date_format`` — маска для человека («ДД.ММ.ГГГГ»), а не шаблон
``strptime``: её правит АДМ в форме. Перевод — ``templates.date_pattern``.

**Счёт организации** — IBAN (KZ + 18 знаков, mod 97 — та же проверка, что у
счетов контрагентов), банк, БИК, валюта и шаблон, по которому разбирается
его выписка (ТЗ §11.2: счёт «определяет шаблон разбора»). IBAN уникален —
вместе с архивными: счёт, выведенный в архив, возвращается из архива, а не
заводится вторым (E-BNK-01).
"""

from __future__ import annotations

from django.db import models
from django.db.models import F, Q

from .core import BppModel, VersionedModel

__all__ = [
    "AmountMode",
    "BankImport",
    "BankImportStatus",
    "BankStatementLine",
    "LineMatchStatus",
    "OrgBankAccount",
    "PaymentMatch",
    "PaymentMatchState",
    "StatementFormat",
    "StatementTemplate",
]


class StatementFormat(models.TextChoices):
    ONEC = "onec", "1С (1CClientBankExchange, .txt)"
    XLSX = "xlsx", "Excel (.xlsx)"
    CSV = "csv", "CSV"


class AmountMode(models.TextChoices):
    SIGNED = "signed", "Одна колонка суммы со знаком"
    SPLIT = "split", "Колонки «Дебет» и «Кредит»"


class StatementTemplate(VersionedModel):
    name = models.CharField(max_length=255)
    format = models.CharField(max_length=8, choices=StatementFormat.choices)
    # cp1251 — 1С и CSV банк-клиентов, utf-8 — xlsx (кодировку xlsx задаёт
    # сама книга, поле для неё справочное). Умолчание по формату ставит
    # сервис (``services/bank/settings.py``).
    encoding = models.CharField(max_length=32, default="cp1251", db_default="cp1251")
    delimiter = models.CharField(max_length=4, default=";", db_default=";", blank=True)
    date_format = models.CharField(max_length=32, default="ДД.ММ.ГГГГ",
                                   db_default="ДД.ММ.ГГГГ")
    columns = models.JSONField(default=dict, blank=True)
    amount_mode = models.CharField(max_length=8, choices=AmountMode.choices,
                                   default=AmountMode.SIGNED, db_default=AmountMode.SIGNED)
    is_active = models.BooleanField(default=True, db_default=True)

    class Meta:
        ordering = ("name", "created_at")
        verbose_name = "Шаблон выписки"
        verbose_name_plural = "Шаблоны выписок"

    def __str__(self) -> str:
        return self.name


class OrgBankAccount(VersionedModel):
    iban = models.CharField(max_length=34)
    bank_name = models.CharField(max_length=255, default="", blank=True)
    bic = models.CharField(max_length=11)
    currency = models.CharField(max_length=3, default="KZT", db_default="KZT")
    template = models.ForeignKey(StatementTemplate, on_delete=models.PROTECT,
                                 related_name="accounts")
    is_active = models.BooleanField(default=True, db_default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["iban"], name="uq_bpp_org_account_iban"),
        ]
        ordering = ("-is_active", "bank_name", "iban")
        verbose_name = "Банковский счёт организации"
        verbose_name_plural = "Банковские счета организации"

    def __str__(self) -> str:
        return f"{self.bank_name} {self.iban}".strip()


# ── загрузка выписки (A4.1, план этапа 3 A, задача 3) ──────────────────

class BankImportStatus(models.TextChoices):
    """ТЗ §15.5: «Загружена → (автосверка) → Сверена → Отменена». Автосверка
    (A4.2) переводит «Загружена» в «Сверена» (D-S3-2). «Обрабатывается» и «Ошибка» —
    состояния фонового разбора, которые опрашивает экран."""

    PROCESSING = "processing", "Обрабатывается"
    LOADED = "loaded", "Загружена"
    RECONCILED = "reconciled", "Сверена"
    FAILED = "failed", "Ошибка загрузки"
    CANCELLED = "cancelled", "Отменена"


class LineMatchStatus(models.TextChoices):
    """Статус сопоставления строки выписки со счетами (ТЗ §11.3, A4.2).
    Новая строка — «Не сопоставлена»; сверка переводит её дальше."""

    UNMATCHED = "unmatched", "Не сопоставлена"
    MATCHED = "matched", "Сопоставлена"
    NEEDS_REVIEW = "needs_review", "Требует проверки"
    EXCLUDED = "excluded", "Исключена"


class PaymentMatchState(models.TextChoices):
    ACTIVE = "active", "Действует"
    REVIEW = "review", "На проверке"
    CANCELLED = "cancelled", "Отменено"


class BankImport(BppModel):
    """Загрузка выписки банк-клиента ``ВП-ГГГГ-0001`` (ТЗ §11.2, L-07).

    Файл выписки — в ``apps.files`` (владелец ``bpp.bank_import``, тип
    ``bank_statement``) и после загрузки не меняется. ``source`` — копия его
    байтов только на время фонового разбора: прочитать файл обратно из
    ``apps.files`` модулю нечем (подсистема выдаёт наружу лишь ссылку на
    скачивание, и каждая её выдача — строка журнала скачиваний), а брокер
    Celery 20 МБ не повезёт. Разбор закончился (удачно или нет) — столбец
    очищается.

    Итоги: ``rows_total`` — документов (строк данных) в файле, ``debits`` —
    из них списаний со счёта организации, ``rows_done`` — сколько списаний
    уже записано (прогресс для опроса экрана, ``rows_done / debits``),
    ``duplicates`` — пропущенных дублей (BR-075), ``errors`` — «Строка N:
    …» по нераспознанным строкам, ``failure`` — почему не загрузилась вся
    выписка (статус «Ошибка загрузки»). Строки неудавшейся загрузки
    отменяются (``cancelled_at``) — иначе они держали бы ключи дублей, и
    повторная загрузка той же выписки пропустила бы их как «уже
    загруженные».
    """

    number = models.CharField(max_length=20, unique=True)
    account = models.ForeignKey(OrgBankAccount, on_delete=models.PROTECT, related_name="imports")
    format = models.CharField(max_length=8, choices=StatementFormat.choices)
    period_from = models.DateField()
    period_to = models.DateField()
    status = models.CharField(max_length=16, choices=BankImportStatus.choices,
                              default=BankImportStatus.PROCESSING,
                              db_default=BankImportStatus.PROCESSING)
    filename = models.CharField(max_length=255, default="", blank=True)
    rows_total = models.PositiveIntegerField(default=0, db_default=0)
    rows_done = models.PositiveIntegerField(default=0, db_default=0)
    debits = models.PositiveIntegerField(default=0, db_default=0)
    duplicates = models.PositiveIntegerField(default=0, db_default=0)
    errors = models.JSONField(default=list, blank=True)
    failure = models.TextField(default="", blank=True)
    comment = models.TextField(default="", blank=True)
    author_id = models.IntegerField(null=True, blank=True)
    # Разбор взят воркером (``imports.run_import``): повторная доставка той
    # же задачи видит непустое поле и не разбирает файл второй раз.
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    source = models.BinaryField(default=b"", blank=True, editable=False)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(period_to__gte=F("period_from")),
                                   name="ck_bpp_bankimport_period"),
        ]
        indexes = [
            models.Index(fields=["account", "period_from", "period_to"],
                         name="ix_bpp_bankimport_account"),
            models.Index(fields=["status", "created_at"], name="ix_bpp_bankimport_status"),
        ]
        ordering = ("-created_at",)
        verbose_name = "Загрузка выписки"
        verbose_name_plural = "Загрузки выписок"

    def __str__(self) -> str:
        return self.number


class BankStatementLine(BppModel):
    """Строка выписки — одно списание со счёта организации (ТЗ §11.3 п.2).

    Дубль (BR-075) — та же операция по ключу «счёт организации + дата + №
    документа + сумма + БИН получателя» (``dedup_hash``, SHA-256). Ключ
    уникален среди НЕотменённых строк (частичный индекс): отмена загрузки
    (A4.2) ставит ``cancelled_at``, и та же выписка грузится снова. Вставка
    идёт с ``ON CONFLICT DO NOTHING``, поэтому и две одновременные загрузки
    одного файла не дают второй строки.
    """

    bank_import = models.ForeignKey(BankImport, on_delete=models.PROTECT, related_name="lines")
    account = models.ForeignKey(OrgBankAccount, on_delete=models.PROTECT,
                                related_name="statement_lines")
    row_no = models.PositiveIntegerField()
    doc_date = models.DateField()
    doc_number = models.CharField(max_length=64)
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    currency = models.CharField(max_length=3, default="KZT", db_default="KZT")
    recipient_name = models.CharField(max_length=500, default="", blank=True)
    recipient_bin = models.CharField(max_length=32, default="", blank=True)
    recipient_iban = models.CharField(max_length=34, default="", blank=True)
    purpose = models.TextField(default="", blank=True)
    dedup_hash = models.CharField(max_length=64)
    match_status = models.CharField(max_length=16, choices=LineMatchStatus.choices,
                                    default=LineMatchStatus.UNMATCHED,
                                    db_default=LineMatchStatus.UNMATCHED)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    # Сверка (A4.2, D-S4-2): номера счетов из назначения, код причины
    # «Требует проверки» (пусто — замечаний нет), исключение строки.
    found_numbers = models.JSONField(default=list, db_default=[], blank=True)
    review_reason = models.CharField(max_length=32, default="", db_default="", blank=True)
    excluded_comment = models.TextField(default="", db_default="", blank=True)
    excluded_by_id = models.IntegerField(null=True, blank=True)
    excluded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["dedup_hash"], condition=Q(cancelled_at__isnull=True),
                                    name="uq_bpp_statement_line_dedup"),
        ]
        indexes = [
            models.Index(fields=["bank_import", "row_no"], name="ix_bpp_stmtline_import"),
            models.Index(fields=["account", "doc_date"], name="ix_bpp_stmtline_account"),
            models.Index(fields=["match_status"], name="ix_bpp_stmtline_match"),
        ]
        ordering = ("bank_import", "row_no")
        verbose_name = "Строка выписки"
        verbose_name_plural = "Строки выписок"

    def __str__(self) -> str:
        return f"{self.doc_number} {self.doc_date} {self.amount}"


class PaymentMatch(BppModel):
    """Сопоставление строки выписки со счётом (ТЗ §11.3, A4.2).

    Одна строка может делиться между несколькими счетами, один счёт —
    получать несколько строк. В «Оплачено по банку» входят только
    сопоставления ``active`` (D-S4-1); ``review`` ждёт решения ФД,
    ``cancelled`` остаётся в истории. Автор записи — ``created_by``.
    """

    line = models.ForeignKey(BankStatementLine, on_delete=models.PROTECT,
                             related_name="matches", db_index=False)
    invoice = models.ForeignKey("bpp.Invoice", on_delete=models.PROTECT,
                                related_name="payment_matches", db_index=False)
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    manual = models.BooleanField(default=False, db_default=False)
    state = models.CharField(max_length=16, choices=PaymentMatchState.choices,
                             default=PaymentMatchState.ACTIVE,
                             db_default=PaymentMatchState.ACTIVE)
    review_reason = models.CharField(max_length=32, default="", db_default="", blank=True)
    comment = models.TextField(default="", db_default="", blank=True)
    confirmed_by_id = models.IntegerField(null=True, blank=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    cancelled_by_id = models.IntegerField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["line", "invoice"],
                                    condition=~Q(state="cancelled"),
                                    name="uq_bpp_paymatch_line_invoice"),
            models.CheckConstraint(condition=Q(amount__gt=0), name="ck_bpp_paymatch_amount"),
        ]
        indexes = [
            models.Index(fields=["invoice", "state"], name="ix_bpp_paymatch_invoice"),
            models.Index(fields=["line", "state"], name="ix_bpp_paymatch_line"),
        ]
        ordering = ("created_at",)
        verbose_name = "Сопоставление платежа"
        verbose_name_plural = "Сопоставления платежей"

    def __str__(self) -> str:
        return f"{self.line_id} -> {self.invoice_id} {self.amount}"
