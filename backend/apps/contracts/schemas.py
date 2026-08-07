"""Pydantic-схемы HTTP-слоя аппки ``contracts``.

``api_view`` валидирует тело запроса схемой из ``body=`` и сериализует
возвращённую схему в ответ (см. ``htqweb/http.py``).

Соглашение по PATCH-схемам: все поля ``Optional[...] = None``, и ``None``
означает «поле не пришло», а не «обнулить». Сервисный слой пропускает
``None``-значения при записи (``_apply`` в ``reference_service``), поэтому
обнуляемых полей у этих моделей нет — если такое понадобится, для него
потребуется явный сентинел, а не ``None``.

Денежные поля — ``Decimal``, не ``float``: сумма договора в
``float``-арифметике теряет копейки, а на них сходятся сверки.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Optional

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    TypeAdapter,
    model_validator,
)

from apps.contracts.models import (
    AgreementStatus,
    BudgetStatus,
    CounterpartyStatus,
    InvoiceStatus,
    PaymentType,
)

_ORM = ConfigDict(from_attributes=True)


# ── Country ─────────────────────────────────────────────────────────────

class CountryCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    iso_code: str = Field("", max_length=3)


class CountryUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    iso_code: Optional[str] = Field(None, max_length=3)


class CountryRead(BaseModel):
    model_config = _ORM

    id: int
    name: str
    iso_code: str


# ── Program ─────────────────────────────────────────────────────────────

class ProgramCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    expense_item: str = Field(..., min_length=1, max_length=200)
    code: str = Field("", max_length=50)
    is_active: bool = True


class ProgramUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    expense_item: Optional[str] = Field(None, min_length=1, max_length=200)
    code: Optional[str] = Field(None, max_length=50)
    is_active: Optional[bool] = None


class ProgramRead(BaseModel):
    model_config = _ORM

    id: int
    name: str
    expense_item: str
    code: str
    # Готовая подпись «код название» — как у AdministratorRead, чтобы
    # склейка не повторялась во фронтовых списках. ``name`` при этом
    # остаётся: там, где код уже показан отдельной колонкой, дублировать
    # его в подписи незачем.
    display_name: str
    is_active: bool


# ── Administrator ───────────────────────────────────────────────────────

class AdministratorCreate(BaseModel):
    country_id: int
    project_name: str = Field(..., min_length=1, max_length=200)
    user_id: Optional[int] = None
    is_active: bool = True


class AdministratorUpdate(BaseModel):
    country_id: Optional[int] = None
    project_name: Optional[str] = Field(None, min_length=1, max_length=200)
    user_id: Optional[int] = None
    is_active: Optional[bool] = None


class AdministratorRead(BaseModel):
    model_config = _ORM

    id: int
    country_id: int
    # Страна отдаётся и id, и названием: без ФИО подпись записи — это
    # «проект + страна», и фронтенд не должен собирать её вторым запросом в
    # справочник стран. ``display_name`` — та же подпись целиком, чтобы
    # формат жил в одном месте (свойства на модели).
    country_name: str
    project_name: str
    display_name: str
    user_id: Optional[int]
    is_active: bool


# ── Budget ──────────────────────────────────────────────────────────────

class BudgetUpdate(BaseModel):
    """Правка ШАПКИ бюджета. Сумм здесь нет — они на строках."""

    administrator_id: Optional[int] = None
    period_year: Optional[int] = Field(None, ge=2000, le=2100)
    currency: Optional[str] = Field(None, min_length=3, max_length=3)
    status: Optional[BudgetStatus] = None
    note: Optional[str] = None


class BudgetLineCreate(BaseModel):
    """Добавление программы в уже существующий бюджет."""

    program_id: int
    amount: Decimal = Field(..., ge=0, max_digits=18, decimal_places=2)
    note: str = ""


class BudgetLineUpdate(BaseModel):
    program_id: Optional[int] = None
    amount: Optional[Decimal] = Field(None, ge=0, max_digits=18, decimal_places=2)
    note: Optional[str] = None


class CountryInput(BaseModel):
    """Ссылка на страну ИЛИ данные для её создания.

    Часть составной формы «заявка на бюджет» (см. ``BudgetFullCreate``):
    заполняющий может выбрать существующую страну из списка или вписать
    новую, и форма не должна заставлять его сначала уходить в отдельный
    справочник.
    """

    id: Optional[int] = None
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    iso_code: str = Field("", max_length=3)

    @model_validator(mode="after")
    def _id_or_fields(self):
        if self.id is None and not self.name:
            raise ValueError("нужен либо id страны, либо её название")
        return self


class AdministratorInput(BaseModel):
    id: Optional[int] = None
    project_name: Optional[str] = Field(None, min_length=1, max_length=200)
    country: Optional[CountryInput] = None

    @model_validator(mode="after")
    def _id_or_fields(self):
        if self.id is None and not (self.project_name and self.country):
            raise ValueError(
                "нужен либо id администратора, либо название проекта + страна")
        return self


class ProgramInput(BaseModel):
    id: Optional[int] = None
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    expense_item: Optional[str] = Field(None, min_length=1, max_length=200)
    code: str = Field("", max_length=50)

    @model_validator(mode="after")
    def _id_or_fields(self):
        if self.id is None and not (self.name and self.expense_item):
            raise ValueError(
                "нужен либо id программы, либо название + статья расходов")
        return self


class BudgetProgramLine(BaseModel):
    """Одна бюджетная строка внутри заявки: программа и её собственная сумма.

    Сумма и примечание живут ЗДЕСЬ, а не на заявке целиком: программы в
    одной заявке финансируются по-разному, и общая сумма на всех не имела
    бы смысла — её всё равно пришлось бы делить.

    ``max_digits``/``decimal_places`` дублируют ограничения колонки
    (``Budget.amount`` — ``DecimalField(18, 2)``). Без них 19-значная сумма
    проходит валидацию и падает уже в Postgres ``numeric field overflow`` —
    это ``DataError``, а не ``IntegrityError``, и ``conflict_as`` его не
    ловит, так что заполняющий получал бы 500 вместо 422.
    """

    program: ProgramInput
    amount: Decimal = Field(..., ge=0, max_digits=18, decimal_places=2)
    note: str = ""


class BudgetFullCreate(BaseModel):
    """Заявка на бюджет одним запросом — вместе со справочниками.

    Форма на фронтенде заполняется целиком: администратор (проект +
    страна), НЕСКОЛЬКО программ, у каждой своя сумма, и общие для всей
    заявки год с валютой. Собирать это отдельными POST'ами из браузера
    нельзя — упавший третий запрос оставил бы в справочниках наполовину
    заведённую заявку, которую никто не убирает. Здесь всё создаётся в
    одной транзакции: либо все бюджетные строки, либо ни одной.

    Год и валюта — общие намеренно. Год общий, потому что заявка и есть
    «бюджет проекта на такой-то год»; валюта — потому что иначе у заявки
    не было бы итоговой суммы, а именно её сверяет подписывающий.
    """

    administrator: AdministratorInput
    programs: list[BudgetProgramLine] = Field(..., min_length=1)
    period_year: int = Field(..., ge=2000, le=2100)
    currency: str = Field("KZT", min_length=3, max_length=3)
    note: str = ""

    @model_validator(mode="after")
    def _no_duplicate_programs(self):
        """Одна программа — не больше одной строки в заявке.

        Иначе связка «администратор × программа × год» нарушила бы
        уникальный индекс на второй такой строке, и вся заявка отбилась бы
        409-м про «уже существует» — сообщением про якобы существующий
        бюджет, хотя проблема в самой форме, здесь и сейчас. Ловим до БД и
        отвечаем 422 по адресу.

        Новые программы сверяются по паре «название + статья» (как в
        ``_resolve_program``), без учёта регистра и краевых пробелов: два
        варианта написания одного и того же схлопнутся в одну запись
        справочника и дадут ровно тот же конфликт.
        """
        seen = set()
        for line in self.programs:
            program = line.program
            if program.id is not None:
                key = ("id", program.id)
            else:
                key = ("new", program.name.strip().casefold(),
                       program.expense_item.strip().casefold())
            if key in seen:
                raise ValueError(
                    "одна и та же программа указана в заявке дважды")
            seen.add(key)
        return self


class BudgetLineRead(BaseModel):
    """Строка ВНУТРИ карточки бюджета.

    Года, валюты и администратора здесь нет намеренно: они написаны на самом
    бюджете, и повторять их в каждой строке значило бы раздувать ответ
    данными, которые читающий уже держит в руках.
    """

    id: int
    budget_id: int
    program_id: int
    program_name: str
    expense_item: str
    amount: Decimal
    note: str
    committed: Decimal
    remaining: Decimal


class BudgetRead(BaseModel):
    """Бюджет целиком — шапка, строки и итог.

    Собирается из ``budget_service.serialize_budget``, а не напрямую из
    ORM-объекта: ``allocated``/``committed``/``remaining`` — вычисляемые
    величины (``budget_calc``), колонок под них в таблице нет и быть не
    должно. ``allocated`` — сумма строк, а не хранимое поле.
    """

    id: int
    administrator_id: int
    administrator_name: str
    period_year: int
    currency: str
    status: str
    # Состояние согласования (примесь signoff.Approvable). Отдельная ось от
    # ``status``: бюджет может быть активным и при этом несогласованным.
    # Живёт на бюджете, а не на строке — согласуется он целиком.
    approval_state: str
    note: str
    allocated: Decimal
    committed: Decimal
    remaining: Decimal
    lines: list[BudgetLineRead]
    created_at: datetime
    updated_at: datetime


class BudgetLineFlatRead(BaseModel):
    """Строка ВНЕ своей карточки — с развёрнутым контекстом бюджета.

    Это то, что читает форма договора: там выбирают программу, из которой
    берутся деньги, и ей нужны администратор, год и валюта рядом со строкой,
    а не отдельным запросом за бюджетом.
    """

    id: int
    budget_id: int
    program_id: int
    program_name: str
    expense_item: str
    amount: Decimal
    note: str
    committed: Decimal
    remaining: Decimal
    administrator_id: int
    administrator_name: str
    period_year: int
    currency: str
    # Статус и согласование — родительского бюджета: своих у строки нет.
    budget_status: str
    approval_state: str


# ── Counterparty ────────────────────────────────────────────────────────

_EMAIL = TypeAdapter(EmailStr)


def _blank_or_email(value: str) -> str:
    """Пустая строка — «контакт не заполнен», непустая обязана быть адресом.

    Прямой ``EmailStr`` здесь не годится: он отбивает пустую строку, а
    обязательным e-mail контрагента не является — карточку заводят и по
    одному БИН'у. Но и принимать под видом адреса произвольный текст
    нельзя: именно ради этого поле и вынули из свободных ``contacts``.
    """
    value = value.strip()
    return str(_EMAIL.validate_python(value)) if value else ""


BlankableEmail = Annotated[str, AfterValidator(_blank_or_email)]


class CounterpartyCreate(BaseModel):
    # Казахстанский БИН/ИИН — ровно 12 цифр, но справочник стран у контрагента
    # общий, и у иностранного поставщика номер налогоплательщика другой формы.
    # Поэтому строгий шаблон ^\d{12}$ здесь НЕ ставится: он отбил бы
    # легитимного иностранного контрагента, а такой отказ дороже, чем
    # пропущенная опечатка в номере. Уникальность при этом сохраняется.
    bin_iin: str = Field(..., min_length=1, max_length=32)
    name: str = Field(..., min_length=1, max_length=300)
    country_id: int
    # Признак плательщика НДС, не ставка и не номер свидетельства
    # (см. докстринг модели Counterparty).
    vat: bool = False
    # Контакты — три поля вместо прежней свободной строки; см. докстринг
    # модели Counterparty (там же — почему без должности). Ни одно не
    # обязательно: карточку заводят и по одному БИН'у, контакты дописывают
    # позже.
    contact_name: str = Field("", max_length=200)
    phone: str = Field("", max_length=30)
    email: BlankableEmail = Field("", max_length=254)
    address: str = ""
    status: Optional[CounterpartyStatus] = None


class CounterpartyUpdate(BaseModel):
    bin_iin: Optional[str] = Field(None, min_length=1, max_length=32)
    name: Optional[str] = Field(None, min_length=1, max_length=300)
    country_id: Optional[int] = None
    vat: Optional[bool] = None
    contact_name: Optional[str] = Field(None, max_length=200)
    phone: Optional[str] = Field(None, max_length=30)
    email: Optional[BlankableEmail] = Field(None, max_length=254)
    address: Optional[str] = None
    status: Optional[CounterpartyStatus] = None


class CounterpartyFullCreate(BaseModel):
    """Карточка контрагента вместе со страной — одним запросом.

    Та же причина, что и у ``BudgetFullCreate``: страна в форме выбирается
    из списка ИЛИ вписывается новой, и заводить её отдельным POST'ом из
    браузера значило бы оставить её висеть, если создание самого
    контрагента следом упадёт (например, на дубле БИН/ИИН).
    """

    bin_iin: str = Field(..., min_length=1, max_length=32)
    name: str = Field(..., min_length=1, max_length=300)
    country: CountryInput
    vat: bool = False
    contact_name: str = Field("", max_length=200)
    phone: str = Field("", max_length=30)
    email: BlankableEmail = Field("", max_length=254)
    address: str = ""
    status: Optional[CounterpartyStatus] = None


class CounterpartyRead(BaseModel):
    model_config = _ORM

    id: int
    bin_iin: str
    name: str
    country_id: int
    vat: bool
    # Словесная форма признака («с НДС» / «без НДС») — с модели, чтобы у
    # одного булева значения не завелось двух переводов.
    vat_label: str
    contact_name: str
    phone: str
    email: str
    # Однострочная склейка трёх полей выше — с модели, чтобы реестр и
    # карточка не собирали её порознь и по-разному (см. Counterparty).
    contact_summary: str
    address: str
    status: str
    approval_state: str
    created_at: datetime
    updated_at: datetime


# ── Agreement ───────────────────────────────────────────────────────────

class AgreementCreate(BaseModel):
    # Ссылка на СТРОКУ бюджета, а не на бюджет: деньги выделены программе.
    number: str = Field(..., min_length=1, max_length=100)
    name: str = Field(..., min_length=1, max_length=300)
    budget_line_id: int
    counterparty_id: int
    amount: Decimal = Field(..., gt=0)
    payment_type: PaymentType
    currency: str = Field("KZT", min_length=3, max_length=3)
    signed_date: Optional[date] = None
    status: Optional[AgreementStatus] = None


class AgreementUpdate(BaseModel):
    """Статуса здесь нет намеренно: он меняется только через
    ``POST /agreements/{id}/status``, где проверяется допустимость перехода
    (``agreement_service.ALLOWED_TRANSITIONS``). Приняв статус в PATCH, мы
    открыли бы обход этой таблицы."""

    number: Optional[str] = Field(None, min_length=1, max_length=100)
    name: Optional[str] = Field(None, min_length=1, max_length=300)
    budget_line_id: Optional[int] = None
    counterparty_id: Optional[int] = None
    amount: Optional[Decimal] = Field(None, gt=0)
    payment_type: Optional[PaymentType] = None
    currency: Optional[str] = Field(None, min_length=3, max_length=3)
    signed_date: Optional[date] = None


class AgreementStatusChange(BaseModel):
    status: AgreementStatus


class AgreementRead(BaseModel):
    """Собирается из ``agreement_service.serialize_agreement``: администратор
    и программа отдаются развёрнуто, хотя на договоре их колонок нет —
    читаются через строку бюджета.

    ``budget_line_id`` — то, на что договор ссылается на самом деле;
    ``budget_id`` рядом отдаётся для ссылки на карточку бюджета."""

    id: int
    number: str
    name: str
    budget_line_id: int
    budget_id: int
    administrator_id: int
    administrator_name: str
    program_id: int
    program_name: str
    expense_item: str
    period_year: int
    counterparty_id: int
    counterparty_name: str
    counterparty_bin_iin: str
    payment_type: str
    amount: Decimal
    currency: str
    file_id: Optional[str]
    signed_date: Optional[date]
    status: str
    approval_state: str
    created_by: Optional[int]
    created_at: datetime
    updated_at: datetime


# ── Invoice (счёт на оплату без договора) ───────────────────────────────

class InvoiceCreate(BaseModel):
    # Ссылка на СТРОКУ бюджета, не на бюджет: деньги выделены программе (как
    # у договора). ``number`` и ``status`` у счёта не принимаются: он всегда
    # создаётся черновиком, а жизненный цикл идёт только через /status.
    # ``currency`` снимается со строки бюджета на сервере.
    name: str = Field(..., min_length=1, max_length=300)
    note: str = ""
    budget_line_id: int
    counterparty_id: int
    amount: Decimal = Field(..., gt=0)


class InvoiceUpdate(BaseModel):
    """Ни статуса (только через ``POST /invoices/{id}/status``), ни валюты
    (она привязана к бюджету строки) здесь нет — по тем же причинам, что и у
    ``AgreementUpdate``."""

    name: Optional[str] = Field(None, min_length=1, max_length=300)
    note: Optional[str] = None
    budget_line_id: Optional[int] = None
    counterparty_id: Optional[int] = None
    amount: Optional[Decimal] = Field(None, gt=0)


class InvoiceStatusChange(BaseModel):
    status: InvoiceStatus


class InvoiceRead(BaseModel):
    """Собирается из ``invoice_service.serialize_invoice``: администратор и
    программа развёрнуты, хотя на счёте их колонок нет — читаются через строку
    бюджета. ``budget_id`` рядом — для ссылки на карточку бюджета."""

    id: int
    name: str
    note: str
    budget_line_id: int
    budget_id: int
    administrator_id: int
    administrator_name: str
    program_id: int
    program_name: str
    expense_item: str
    period_year: int
    counterparty_id: int
    counterparty_name: str
    counterparty_bin_iin: str
    amount: Decimal
    currency: str
    file_id: Optional[str]
    status: str
    approval_state: str
    created_by: Optional[int]
    created_at: datetime
    updated_at: datetime
