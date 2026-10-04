"""Ручки справочников — каждая под гейтом модуля refdata с явным уровнем.

Чтение — ``read``. Запись — ``write`` плюс проверка «управляющая компания»
(``services/editing.can_edit``): гейт модуля отвечает «может ли роль»,
проверка компании — «здесь ли» (D-03). Удаления нет — только архив.
"""

from __future__ import annotations

from datetime import date, timedelta

from django.db import IntegrityError, transaction
from django.forms.models import model_to_dict
from django.http import Http404

from htqweb.errors import DomainError
from htqweb.http import api_view, json_error, uuid_or_404

from . import models, schemas
from .services import articles as article_rules
from .services import editing
from .services import production_calendar as calendar

READ_ONLY_FIELDS = {"id", "created_at", "updated_at"}


def _row(obj) -> dict:
    data = model_to_dict(obj)
    data["id"] = str(obj.id)
    for key, value in list(data.items()):
        if hasattr(value, "quantize"):
            data[key] = str(value)
        elif hasattr(value, "isoformat"):
            data[key] = value.isoformat()
    if "group" in data:
        data["group_id"] = str(data.pop("group"))
    if "parent" in data:
        parent = data.pop("parent")
        data["parent_id"] = str(parent) if parent else None
    return data


def _deny_unless_editor(request) -> None:
    company = getattr(request, "company", None) or {}
    if not editing.can_edit(request.token, company.get("slug")):
        raise DomainError(
            "E-REF-01",
            "Справочники ведёт управляющая компания. Откройте раздел на её "
            "поддомене или обратитесь к финансовому директору.",
            status=403)


def _save(obj) -> dict:
    try:
        with transaction.atomic():
            obj.save()
    except IntegrityError as exc:
        raise DomainError("E-REF-02", "Запись с таким кодом уже есть в справочнике.",
                          status=422) from exc
    return _row(obj)


def _listing_can_edit(request) -> bool:
    company = getattr(request, "company", None) or {}
    return editing.can_edit(request.token, company.get("slug"))


def _collection(model, schema_in, order: str):
    @api_view(methods=("GET",), module="refdata", level="read")
    def listing(request):
        # На КАЖДУЮ строку, а не одним полем на весь ответ: ручка отдаёт
        # голый список (без обёртки {items,...}), и добавлять обёртку ради
        # одного булева значения — лишняя переделка фронта; значение у всех
        # строк одно и то же (одна роль, одна компания на запрос), поэтому
        # дублирование стоит одного вычисления can_edit() на запрос.
        can_edit_flag = _listing_can_edit(request)
        rows = model.objects.all().order_by(order)
        if request.GET.get("active") == "1" and hasattr(model, "is_active"):
            rows = rows.filter(is_active=True)
        return [{**_row(obj), "can_edit": can_edit_flag} for obj in rows]

    @api_view(methods=("POST",), module="refdata", level="write", body=schema_in, status=201)
    def create(request, data):
        _deny_unless_editor(request)
        if model is models.Article:
            article_rules.check_group(data.group_id)
            article_rules.check_parent(data.group_id, data.parent_id)
        obj = model(**data.model_dump())
        if model is models.ExchangeRate:
            obj.source = models.RateSource.MANUAL
        return _save(obj)

    def dispatch(request):
        if request.method == "GET":
            return listing(request)
        if request.method == "POST":
            return create(request)
        return json_error("Method Not Allowed", 405)

    return dispatch


def _item(model, schema_patch):
    @api_view(methods=("PATCH",), module="refdata", level="write", body=schema_patch)
    def patch(request, obj_id: str, data):
        _deny_unless_editor(request)
        obj = model.objects.filter(pk=uuid_or_404(obj_id)).first()
        if obj is None:
            raise Http404("Запись справочника не найдена")
        for key, value in data.model_dump(exclude_unset=True).items():
            setattr(obj, key, value)
        # Досюда дошёл только редактор (_deny_unless_editor выше) — можно
        # без повторного вычисления.
        return {**_save(obj), "can_edit": True}

    def dispatch(request, obj_id: str):
        if request.method == "PATCH":
            return patch(request, obj_id=obj_id)
        return json_error("Method Not Allowed", 405)

    return dispatch


countries = _collection(models.Country, schemas.CountryIn, "name")
country_item = _item(models.Country, schemas.CountryPatch)
currencies = _collection(models.Currency, schemas.CurrencyIn, "code")
currency_item = _item(models.Currency, schemas.CurrencyPatch)
rates = _collection(models.ExchangeRate, schemas.RateIn, "-on_date")
vat = _collection(models.VatRate, schemas.VatIn, "country_code")
mrp = _collection(models.MrpValue, schemas.MrpIn, "date_from")
uoms = _collection(models.Uom, schemas.UomIn, "name")
uom_item = _item(models.Uom, schemas.UomPatch)
article_groups = _collection(models.ArticleGroup, schemas.ArticleGroupIn, "name")
article_group_item = _item(models.ArticleGroup, schemas.ArticleGroupPatch)
articles = _collection(models.Article, schemas.ArticleIn, "code")
article_item = _item(models.Article, schemas.ArticlePatch)


# ── производственный календарь РК (A7.1, D-S7-1) ────────────────────────
# Чтение — самообслуживание (access/self_service.py, причина ``open``): виджет
# календаря нужен каждому сотруднику, а у ``employee-basic`` модуля refdata нет.
# Правка — гейт модуля ``write`` + узел ``refdata.production_calendar`` строго
# ``edit`` (без наследования от модуля) + управляющая компания.

MAX_RANGE_DAYS = 370
CALENDAR_NODE = "refdata.production_calendar"


def _bad_param(name: str, message: str):
    return json_error([{"type": "value_error", "loc": ["query", name], "msg": message}], 422)


def _date_query(request, name: str):
    raw = request.GET.get(name)
    if raw in (None, ""):
        return None, None
    try:
        return date.fromisoformat(raw), None
    except ValueError:
        return None, _bad_param(name, "Input should be a valid date in YYYY-MM-DD format")


@api_view(methods=("GET",))
def production_calendar(request):
    from django.utils import timezone

    from apps.core.services import require_service

    require_service("refdata")
    start, err = _date_query(request, "date__gte")
    if err:
        return err
    end, err = _date_query(request, "date__lte")
    if err:
        return err
    start = start or timezone.localdate().replace(day=1)
    end = end or (start + timedelta(days=31))
    if start > end:
        return json_error("date__gte must be before date__lte", 400)
    if (end - start).days > MAX_RANGE_DAYS:
        return json_error("Date range is too large", 400)
    company = getattr(request, "company", None) or {}
    can_edit = editing.can_edit(request.token, company.get("slug"), CALENDAR_NODE, flags=("edit",))
    return [schemas.ProductionDayResponse.model_validate({**row, "can_edit": can_edit})
            for row in calendar.list_production_days(start, end)]


@api_view(methods=("PATCH",), body=schemas.ProductionDayUpdate, module="refdata", level="write")
def production_day_detail(request, target_date: str, data: schemas.ProductionDayUpdate):
    company = getattr(request, "company", None) or {}
    if not editing.can_edit(request.token, company.get("slug"), CALENDAR_NODE, flags=("edit",)):
        raise DomainError(
            "E-REF-03",
            "Производственный календарь правят операционный директор и HR "
            "управляющей компании на её поддомене.",
            status=403)
    try:
        parsed = date.fromisoformat(target_date)
    except ValueError:
        return _bad_param("target_date", "Input should be a valid date in YYYY-MM-DD format")
    day = calendar.update_production_day(parsed, day_type=data.day_type, note=data.note)
    return {**schemas.ProductionDayResponse.model_validate(day).model_dump(mode="json"),
            "can_edit": True}
