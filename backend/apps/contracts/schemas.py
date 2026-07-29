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
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from apps.contracts.models import (
    AgreementStatus,
    BudgetStatus,
    CounterpartyStatus,
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

class BudgetCreate(BaseModel):
    administrator_id: int
    program_id: int
    amount: Decimal = Field(..., ge=0)
    period_year: int = Field(..., ge=2000, le=2100)
    currency: str = Field("KZT", min_length=3, max_length=3)
    note: str = ""


class BudgetUpdate(BaseModel):
    administrator_id: Optional[int] = None
    program_id: Optional[int] = None
    amount: Optional[Decimal] = Field(None, ge=0)
    period_year: Optional[int] = Field(None, ge=2000, le=2100)
    currency: Optional[str] = Field(None, min_length=3, max_length=3)
    status: Optional[BudgetStatus] = None
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


class BudgetFullCreate(BaseModel):
    """Заявка на бюджет одним запросом — вместе со справочниками.

    Форма на фронтенде заполняется целиком: администратор (проект +
    страна), программа (название, статья расходов) и сама сумма. Собирать
    это четырьмя отдельными POST'ами из браузера нельзя — упавший третий
    запрос оставил бы в справочниках наполовину заведённую заявку, которую
    никто не убирает. Здесь всё создаётся в одной транзакции.
    """

    administrator: AdministratorInput
    program: ProgramInput
    amount: Decimal = Field(..., ge=0)
    period_year: int = Field(..., ge=2000, le=2100)
    currency: str = Field("KZT", min_length=3, max_length=3)
    note: str = ""


class BudgetRead(BaseModel):
    """Собирается из ``budget_service.serialize_budget``, а не напрямую из
    ORM-объекта: ``committed``/``remaining`` — вычисляемые величины
    (``budget_calc``), колонок под них в таблице нет и быть не должно."""

    id: int
    administrator_id: int
    administrator_name: str
    program_id: int
    program_name: str
    expense_item: str
    amount: Decimal
    currency: str
    period_year: int
    status: str
    # Состояние согласования (примесь signoff.Approvable). Отдельная ось от
    # ``status``: строка может быть активной и при этом несогласованной.
    approval_state: str
    note: str
    committed: Decimal
    remaining: Decimal
    created_at: datetime
    updated_at: datetime


# ── Counterparty ────────────────────────────────────────────────────────

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
    contacts: str = ""
    address: str = ""
    status: Optional[CounterpartyStatus] = None


class CounterpartyUpdate(BaseModel):
    bin_iin: Optional[str] = Field(None, min_length=1, max_length=32)
    name: Optional[str] = Field(None, min_length=1, max_length=300)
    country_id: Optional[int] = None
    vat: Optional[bool] = None
    contacts: Optional[str] = None
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
    contacts: str = ""
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
    contacts: str
    address: str
    status: str
    approval_state: str
    created_at: datetime
    updated_at: datetime


# ── Agreement ───────────────────────────────────────────────────────────

class AgreementCreate(BaseModel):
    number: str = Field(..., min_length=1, max_length=100)
    name: str = Field(..., min_length=1, max_length=300)
    budget_id: int
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
    budget_id: Optional[int] = None
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
    читаются через бюджетную строку."""

    id: int
    number: str
    name: str
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
