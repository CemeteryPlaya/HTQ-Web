"""Pydantic models + validator for a form template's ``schema_json``.

Copied verbatim from ``services/requests/app/services/form_schema.py``: it is
pure pydantic with no framework dependency, and it defines the 21 widget
types the form builder emits (20 ported ones plus ``budget_line_ref``, added
in the monolith). Every one of them is a shape the frontend already produces,
so "tidying" the union here would silently reject templates that exist in the
database.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, Field, model_validator

_KEY = r"^[a-zA-Z][a-zA-Z0-9_]*$"


class _BaseField(BaseModel):
    key: str = Field(..., min_length=1, max_length=64, pattern=_KEY)
    label: str = Field(..., min_length=1, max_length=200)
    required: bool = False
    # Кто заполняет поле. ``initiator`` — при подаче, как все поля формы.
    # ``approver`` — согласующий на СВОЁМ рабочем шаге, уже на согласовании:
    # у заявки на закуп это поставщик и согласованная сумма, которых
    # инициатор знать не может. Такое поле инициатору не показывается и при
    # подаче не требуется (``value_validation``), а заполняется через
    # ``instances/<id>/stage-values/`` тем, чей активный этап этого требует
    # (``approval_hooks._requirement_fields`` → ``signoff.requirement_key``).
    filled_by: Literal["initiator", "approver"] = "initiator"
    # Значение обязано совпадать с другим полем формы — путь ``key`` или
    # ``group.key`` (у неповторяемой группы). Правило для сумм: «Сумма по
    # счёту» = «Согласованная сумма», иначе CFO утверждает одно, а платят
    # другое. Проверяется там же, где обязательность: при подаче для полей
    # инициатора и на шаге согласующего для его полей (``value_validation``,
    # ``approval_hooks._check_requirement``). Только number/money — сравнивать
    # строки «на равенство» бессмысленно, а даты сюда не просили.
    must_equal: str | None = Field(None, max_length=129)


class TextField(_BaseField):
    type: Literal["text"] = "text"
    max: int | None = Field(None, ge=1)


class NumberField(_BaseField):
    type: Literal["number"] = "number"
    min: float | None = None
    max: float | None = None
    contributes_to_total: bool = False


class MoneyField(_BaseField):
    type: Literal["money"] = "money"
    currency: str = Field("KZT", min_length=3, max_length=3)
    contributes_to_total: bool = False


class DateField(_BaseField):
    type: Literal["date"] = "date"


class DropdownField(_BaseField):
    type: Literal["dropdown"] = "dropdown"
    options: list[str] = Field(..., min_length=1)
    multiple: bool = False


class CheckboxField(_BaseField):
    type: Literal["checkbox"] = "checkbox"


class UserRefField(_BaseField):
    type: Literal["user_ref"] = "user_ref"
    multiple: bool = False


class ProjectRefField(_BaseField):
    type: Literal["project_ref"] = "project_ref"


class DepartmentRefField(_BaseField):
    type: Literal["department_ref"] = "department_ref"


class FileField(_BaseField):
    type: Literal["file"] = "file"
    accept: str = "pdf,jpg,png"
    max_size_mb: int = Field(20, ge=1, le=50)


class TableColumn(BaseModel):
    key: str = Field(..., min_length=1, max_length=64, pattern=_KEY)
    label: str = Field("", max_length=200)
    type: Literal["text", "number", "money", "date"] = "text"


class TableField(_BaseField):
    type: Literal["table"] = "table"
    columns: list[TableColumn] = Field(..., min_length=1)

    @model_validator(mode="after")
    def _unique_columns(self) -> "TableField":
        keys = [c.key for c in self.columns]
        if len(keys) != len(set(keys)):
            raise ValueError(f"duplicate column keys in table '{self.key}'")
        return self


class SignatureField(_BaseField):
    type: Literal["signature"] = "signature"


class FormulaField(_BaseField):
    type: Literal["formula"] = "formula"
    expr: str = Field(..., min_length=1)
    contributes_to_total: bool = False


class AmountField(_BaseField):
    """Multi-currency money (Lark `amount`)."""
    type: Literal["amount"] = "amount"
    currencies: list[str] = Field(..., min_length=1)
    amount_in_words: bool = False
    decimals: int = Field(2, ge=0, le=4)
    thousand_separator: bool = True
    contributes_to_total: bool = False
    min: float | None = None
    max: float | None = None

    @model_validator(mode="after")
    def _currencies_are_iso(self) -> "AmountField":
        for c in self.currencies:
            if len(c) != 3 or not c.isalpha() or c != c.upper():
                raise ValueError(f"currency '{c}' must be a 3-letter uppercase ISO code")
        return self


class ParagraphField(_BaseField):
    type: Literal["paragraph"] = "paragraph"
    max: int | None = Field(None, ge=1)


class StaticTextField(_BaseField):
    """Static display text (Lark `text`) — no input."""
    type: Literal["static_text"] = "static_text"
    content: str = Field(..., min_length=1)


class SerialField(_BaseField):
    type: Literal["serial"] = "serial"
    prefix: str = ""


class LinkRefField(_BaseField):
    """Reference to another approval/request (Lark `connect`)."""
    type: Literal["link_ref"] = "link_ref"
    template_slug: str | None = None
    multiple: bool = False


class ReferenceField(_BaseField):
    """Lookup into a reference data source (Lark `mutableGroup` / Data from Base)."""
    type: Literal["reference"] = "reference"
    source: str = Field(..., min_length=1, max_length=64)
    column: str = Field(..., min_length=1, max_length=64)
    depends_on: str | None = None
    multiple: bool = False


class BudgetLineRefField(_BaseField):
    """Строка бюджета из ``apps.contracts`` — каскад «администратор → программа».

    Хранит ОДИН ``budget_line_id`` (int), а не пару «администратор + программа»:
    строка бюджета — это уже «администратор × год × программа», и две ссылки
    рядом были бы второй версией правды о том, из какого кармана заявка (тот
    же довод, что у ``contracts.Agreement.budget_line``).

    Настроек у виджета нет: список строк берётся у contracts целиком
    (``GET /api/contracts/v1/budget-lines``), а проверка выбранного id и его
    подпись идут через ``budget_line_refs`` → ``apps.contracts.interface``.
    """
    type: Literal["budget_line_ref"] = "budget_line_ref"


class SupplierQuotesField(_BaseField):
    """Сравнительная таблица поставщиков (СТ) — то, что закупщик сводит
    руками в Excel: строки = позиции заявки, колонки = поставщики, в
    клетках цены за единицу.

    Значение:

        {"suppliers": [{"name": …, "note": …, "prices": [98500, …]}],
         "chosen": 0,                  ← индекс выбранного поставщика
         "total": "98500.00",          ← ВЫВОДИТСЯ сервером
         "supplier_name": "ТОО …"}     ←  (``services/quotes.py``)

    ``total`` и ``supplier_name`` не вводятся, а считаются при сохранении:
    так из «выбрал поставщика» сразу следует сумма заявки, и никто не
    перепечатывает её второй раз. Благодаря им путь ``<ключ>.total`` —
    обычное денежное поле для ``must_equal`` и ``contributes_to_total``,
    и остальным механизмам про этот виджет знать не нужно.

    ``items_field`` — ключ ПОВТОРЯЕМОЙ группы, чьи строки становятся
    строками таблицы (у заявки на закуп это «Позиции закупа»). Цена в
    клетке — за единицу; итог по поставщику = Σ цена × количество, а
    количество берётся из той же группы.
    """
    type: Literal["supplier_quotes"] = "supplier_quotes"
    items_field: str = Field(..., min_length=1, max_length=64)
    # Колонка количества внутри ``items_field``; пусто — считать по одной
    # единице на строку (у группы без количества умножать не на что).
    quantity_key: str = ""
    currency: str = Field("KZT", min_length=3, max_length=3)
    contributes_to_total: bool = False


class GroupField(_BaseField):
    """Repeatable nested widget group (Lark `fieldList`)."""
    type: Literal["group"] = "group"
    fields: list["FieldUnion"] = Field(..., min_length=1)
    repeatable: bool = True
    summarize_keys: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_group(self) -> "GroupField":
        keys = [f.key for f in self.fields]
        if len(keys) != len(set(keys)):
            raise ValueError(f"duplicate field keys in group '{self.key}'")
        missing = [k for k in self.summarize_keys if k not in set(keys)]
        if missing:
            raise ValueError(f"summarize_keys {missing} not in group '{self.key}'")
        return self


FieldUnion = Annotated[
    Union[
        TextField, NumberField, MoneyField, AmountField, DateField, DropdownField,
        CheckboxField, UserRefField, ProjectRefField, DepartmentRefField, FileField,
        TableField, SignatureField, FormulaField, ParagraphField, StaticTextField,
        SerialField, LinkRefField, ReferenceField, BudgetLineRefField,
        SupplierQuotesField, GroupField,
    ],
    Field(discriminator="type"),
]

GroupField.model_rebuild()


class Condition(BaseModel):
    field: str = Field(..., min_length=1)
    op: Literal["is", "is_not", "gt", "lt", "contains"] = "is"
    value: Any = None


class DisplayCondition(BaseModel):
    """Show `target` when its `conditions` match (Lark `displayCondition`)."""
    target: str = Field(..., min_length=1)
    match: Literal["all", "any"] = "all"
    conditions: list[Condition] = Field(..., min_length=1)


class FormSchema(BaseModel):
    fields: list[FieldUnion] = Field(default_factory=list)
    display_conditions: list[DisplayCondition] = Field(default_factory=list)

    @model_validator(mode="after")
    def _unique_keys(self) -> "FormSchema":
        keys = [f.key for f in self.fields]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate field keys in form schema")
        return self

    @model_validator(mode="after")
    def _validate_display_conditions(self) -> "FormSchema":
        known = self.all_keys
        for dc in self.display_conditions:
            if dc.target not in known:
                raise ValueError(f"display condition target '{dc.target}' is not a known field")
            for c in dc.conditions:
                if c.field not in known:
                    raise ValueError(f"display condition references unknown field '{c.field}'")
        return self

    @model_validator(mode="after")
    def _validate_quotes(self) -> "FormSchema":
        """``items_field`` должен указывать на повторяемую группу, а
        ``quantity_key`` — на её числовую колонку: иначе таблица откроется
        пустой у закупщика, а не у того, кто собирал форму."""
        groups = {f.key: f for f in self.fields
                  if f.type == "group" and f.repeatable}
        for field in self.fields:
            if field.type != "supplier_quotes":
                continue
            group = groups.get(field.items_field)
            if group is None:
                raise ValueError(
                    f"«{field.label}»: поля «{field.items_field}» нет или это "
                    f"не повторяемая группа — строки таблицы брать неоткуда")
            if field.quantity_key and not any(
                    sub.key == field.quantity_key and sub.type in ("number", "money")
                    for sub in group.fields):
                raise ValueError(
                    f"«{field.label}»: в группе «{group.label}» нет числовой "
                    f"колонки «{field.quantity_key}»")
        return self

    @model_validator(mode="after")
    def _validate_must_equal(self) -> "FormSchema":
        """Цель ``must_equal`` должна существовать и быть числом: иначе
        правило молча не сработает, и это узнают только на счёте."""
        numeric = {path for path, field in self.paths().items()
                   if field.type in ("number", "money")}
        for path, field in self.paths().items():
            target = getattr(field, "must_equal", None)
            if not target:
                continue
            if field.type not in ("number", "money"):
                raise ValueError(
                    f"must_equal у «{field.label}»: сравнивать можно только "
                    f"числовые поля")
            if target == path:
                raise ValueError(f"must_equal у «{field.label}»: поле само с собой")
            if target not in numeric:
                raise ValueError(
                    f"must_equal у «{field.label}»: поля «{target}» нет или "
                    f"оно не числовое")
        return self

    def paths(self) -> dict[str, "FieldUnion"]:
        """``{"key" | "group.key": поле}`` — все поля с путями. Внутрь
        ПОВТОРЯЕМОЙ группы не идём: у её строк нет одного значения, и путь
        туда ничего не обозначает.

        У ``supplier_quotes`` путь ``<ключ>.total`` объявляется денежным
        полем: сумма выбранного предложения лежит в значении виджета, и
        так на неё можно сослаться из ``must_equal`` и сложить в
        ``compute_total``, не обучая эти механизмы новому типу.
        """
        out: dict = {}
        for field in self.fields:
            out[field.key] = field
            if field.type == "group" and not field.repeatable:
                for sub in field.fields:
                    out[f"{field.key}.{sub.key}"] = sub
            elif field.type == "supplier_quotes":
                out[f"{field.key}.total"] = MoneyField(
                    key="total", label=f"{field.label} → сумма выбранного",
                    currency=field.currency,
                    contributes_to_total=field.contributes_to_total)
        return out

    @property
    def keys(self) -> set[str]:
        return {f.key for f in self.fields}

    @property
    def all_keys(self) -> set[str]:
        """All field keys including those nested inside groups."""
        acc: set[str] = set()

        def walk(fields):
            for f in fields:
                acc.add(f.key)
                nested = getattr(f, "fields", None)
                if nested:
                    walk(nested)

        walk(self.fields)
        return acc


def validate_form_schema(data: dict) -> FormSchema:
    """Parse + validate a schema_json dict. Raises ValidationError/ValueError."""
    return FormSchema.model_validate(data)
