"""Личная аналитика по заявкам: «что подавал Я».

Отдельный сервис, а не фильтр к общей статистике (``views.stats_*``),
по одной причине: там срез по компании, и любой параметр «покажи за
человека» рано или поздно наводят на соседа. Здесь пользователь вообще не
назван — ``for_user`` берёт его из токена вызывающей вьюхи, и другого
источника нет.

Три вопроса, на которые отвечает страница:
  • сколько подал и в каком состоянии — по ``status``;
  • на какую сумму — по ``total_amount`` (его считает ``compute_total``
    из полей с ``contributes_to_total``, включая поля блоков);
  • какие вещи и в каком количестве — обход ПОВТОРЯЕМЫХ групп формы.

Про последнее. Движок не знает слова «номенклатура»: строка повторяемой
группы — это просто несколько полей. Поэтому колонки опознаются по типам,
и правило одно на все шаблоны:

  ЧТО     первое текстовое поле строки («ТРУ», «Наименование»);
  СКОЛЬКО поля из ``summarize_keys`` группы, а если их не объявили —
          первое числовое;
  В ЧЁМ   первый выпадающий список («шт», «кг»).

``summarize_keys`` до сих пор лежал в схеме мёртвым (его принимал
конструктор, но не читал никто) — здесь он получает смысл. Единицы входят
в ключ группировки: «5 шт» и «3 кг» — разные строки, складывать их нельзя.
"""

from __future__ import annotations

import datetime as dt
from collections import defaultdict
from decimal import Decimal, InvalidOperation

from django.db.models import Count, Sum
from django.db.models.functions import Coalesce

from ..models import RequestInstance, RequestStatus
from .form_schema import validate_form_schema

# Сколько разных позиций отдаём: страница — не выгрузка, а сводка; за
# полным списком человек идёт в «Управление данными».
TOP_ITEMS = 50


def for_user(user_id: int, *, since: dt.date | None = None) -> dict:
    """Сводка по заявкам, поданным ЭТИМ пользователем.

    ``since`` — левая граница по дате отправки; ``None`` — за всё время.
    Черновики считаются отдельно и в суммы не входят: неотправленное — ещё
    не заявка.
    """
    mine = RequestInstance.objects.filter(initiator_id=user_id)
    if since is not None:
        mine = mine.filter(submitted_at__date__gte=since)

    submitted = mine.exclude(status=RequestStatus.DRAFT)

    by_status = {
        row["status"]: {
            "count": int(row["count"]),
            "amount": str(row["amount"] or Decimal(0)),
        }
        for row in (submitted.values("status")
                    .annotate(count=Count("id"),
                              amount=Coalesce(Sum("total_amount"), Decimal(0))))
    }
    totals = submitted.aggregate(
        count=Count("id"), amount=Coalesce(Sum("total_amount"), Decimal(0)))

    by_template = [
        {
            "template_id": row["template_id"],
            "name": row["template__name"],
            "count": int(row["count"]),
            "amount": str(row["amount"] or Decimal(0)),
        }
        for row in (submitted.values("template_id", "template__name")
                    .annotate(count=Count("id"),
                              amount=Coalesce(Sum("total_amount"), Decimal(0)))
                    .order_by("-count", "template__name"))
    ]

    rows = list(submitted.values("template_version_id", "form_values_json"))
    schemas = _schemas_for(rows)
    return {
        "submitted": int(totals["count"]),
        "drafts": mine.filter(status=RequestStatus.DRAFT).count(),
        "amount": str(totals["amount"] or Decimal(0)),
        "currency": _currency_of(schemas),
        "by_status": by_status,
        "by_template": by_template,
        "items": _items(rows, schemas),
    }


def _currency_of(schemas: dict) -> str:
    """Валюта итога — из СХЕМЫ поля, а не из колонки ``RequestInstance``:
    ту никто никогда не заполнял, и сводка молча оставалась без валюты.
    Объявляет её money-поле, помеченное ``contributes_to_total``, — то
    самое, из которого ``compute_total`` и складывает сумму.

    Одна валюта на всю сводку: складывать разные в один итог нельзя, а
    разносить их — задача, которой никто не ставил. Если шаблоны человека
    объявляют разные валюты, честнее не показать ни одной, чем подписать
    сумму наугад."""
    found = {
        getattr(field, "currency", "")
        for schema in schemas.values()
        for field in (schema.paths().values() if schema else ())
        if field.type == "money" and getattr(field, "contributes_to_total", False)
    }
    found.discard("")
    return found.pop() if len(found) == 1 else ""


def _schemas_for(rows: list[dict]) -> dict:
    """``{version_id: FormSchema | None}`` по версиям, на которых заполнялись
    эти заявки. Именно по версиям, а не по шаблонам: заявка живёт со своей
    формой, и после правки шаблона старые данные должны читаться по той
    схеме, по которой заполнялись."""
    from ..models import RequestFormTemplateVersion

    version_ids = {row["template_version_id"] for row in rows
                   if row["template_version_id"]}
    out = {}
    for pk, schema_json in (RequestFormTemplateVersion.objects
                            .filter(pk__in=version_ids)
                            .values_list("pk", "schema_json")):
        try:
            out[pk] = validate_form_schema(schema_json)
        except ValueError:
            # Версия с невалидной схемой (её приняли до ужесточения правил)
            # не должна ронять всю сводку.
            out[pk] = None
    return out


def _items(rows: list[dict], schemas: dict) -> list[dict]:
    """Позиции из повторяемых групп: ``[{name, unit, quantity, requests}]``."""
    groups_by_version = {pk: _item_groups(schema) if schema else []
                         for pk, schema in schemas.items()}
    acc: dict[tuple[str, str], dict] = defaultdict(
        lambda: {"quantity": Decimal(0), "requests": 0})
    for row in rows:
        groups = groups_by_version.get(row["template_version_id"]) or []
        values = row["form_values_json"] or {}
        seen: set[tuple[str, str]] = set()
        for group_key, spec in groups:
            for item in values.get(group_key) or []:
                if not isinstance(item, dict):
                    continue
                name = str(item.get(spec["name"]) or "").strip()
                if not name:
                    continue
                unit = str(item.get(spec["unit"]) or "").strip() if spec["unit"] else ""
                key = (name, unit)
                acc[key]["quantity"] += _number(item, spec["quantity"])
                if key not in seen:
                    acc[key]["requests"] += 1
                    seen.add(key)

    items = [
        {"name": name, "unit": unit,
         "quantity": _plain(data["quantity"]), "requests": data["requests"]}
        for (name, unit), data in acc.items()
    ]
    items.sort(key=lambda row: (-row["requests"], row["name"]))
    return items[:TOP_ITEMS]


def _item_groups(schema) -> list[tuple[str, dict]]:
    """``[(ключ группы, {name, quantity, unit}), …]`` для повторяемых групп.

    Группа без текстовой колонки пропускается: назвать позицию нечем, а
    строка «(без названия) × 7» в сводке бесполезна.
    """
    out = []
    for field in schema.fields:
        if field.type != "group" or not field.repeatable:
            continue
        name = next((f.key for f in field.fields
                     if f.type in ("text", "paragraph")), None)
        if name is None:
            continue
        declared = [key for key in (field.summarize_keys or [])
                    if any(f.key == key and f.type in ("number", "money")
                           for f in field.fields)]
        quantity = declared or [f.key for f in field.fields
                                if f.type in ("number", "money")][:1]
        unit = next((f.key for f in field.fields if f.type == "dropdown"), None)
        out.append((field.key, {"name": name, "quantity": quantity, "unit": unit}))
    return out


def _number(item: dict, keys: list[str]) -> Decimal:
    """Сумма числовых колонок строки; нечисловое считаем нулём, а не
    роняем сводку — данные приходят из формы, а форма переживала правки."""
    total = Decimal(0)
    for key in keys:
        raw = item.get(key)
        if raw is None or raw == "":
            continue
        try:
            total += Decimal(str(raw))
        except (InvalidOperation, ValueError):
            continue
    return total


def _plain(value: Decimal) -> str:
    """Без хвостовых нулей: «7», а не «7.00» — количество читают глазами."""
    normalized = value.normalize()
    text = format(normalized, "f")
    return text
