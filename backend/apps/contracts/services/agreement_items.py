"""Позиции договора (ТЗ 9.2, BR-033, BR-042).

Позиция либо пришла из заявки на закуп, по которой заключён договор, либо
вписана руками (договор без заявки). Правила — в докстринге модели
``AgreementItem``; здесь их исполнение:

* **остаток по строке заявки** — плановое количество минус то, что уже
  расписано по другим договорам той же заявки (кроме расторгнутых).
  Отдельной таблицы «План закупок» нет: план — это одобренные заявки, и
  их строки адресуются ключом ``"<группа>:<номер>"``
  (``apps.approvals.interface.get_request_items``);
* **сумма позиций = сумма договора**, если договор не открытый. Проверяется
  при сохранении, в котором позиции ПРИСЛАНЫ, и перед отправкой на
  согласование. Черновик без позиций сохранить можно (ТЗ 9.4: «Сохранить
  черновик — только формат») — иначе не заводились бы договоры импортом и
  не сохранялась бы форма на полпути. Обязательность позиций при отправке
  (ТЗ: «минимум одна») пока выключена — см. ``ITEMS_REQUIRED_FOR_APPROVAL``.

``ServiceDisabled`` от approvals не глушится: позиции из заявки без заявки
не проверить, и договор по заявке без approvals не заводится вовсе
(``request_link``).
"""

from __future__ import annotations

from decimal import Decimal

from django.db.models import Sum

from apps.approvals import interface as approvals
from apps.contracts.models import Agreement, AgreementItem, AgreementStatus

ZERO = Decimal("0")


class AgreementItemsViolation(Exception):
    """Позиции договора противоречат заявке или сумме договора (409)."""


def _fmt(value: Decimal) -> str:
    """Количество без хвостовых нулей: «5», «2.5» — его читают глазами."""
    text = format(value.normalize(), "f")
    return text


def request_items(request_id: int, *, exclude_agreement_id: int | None = None) -> list[dict]:
    """Позиции заявки с остатком к законтрактованию.

    ``[{key, name, unit, quantity, contracted, remaining, amount}]``.
    ``exclude_agreement_id`` — договор, который сейчас правят: его
    собственные позиции остатка не уменьшают, иначе правка договора
    упиралась бы в количество, которое он сам и занимает.
    """
    rows = approvals.get_request_items(request_id)
    if rows is None:
        raise AgreementItemsViolation(f"Заявка {request_id} не найдена")

    taken = (AgreementItem.objects
             .filter(agreement__request_id=request_id)
             .exclude(request_item_key="")
             .exclude(agreement__status=AgreementStatus.TERMINATED))
    if exclude_agreement_id is not None:
        taken = taken.exclude(agreement_id=exclude_agreement_id)
    contracted = {row["request_item_key"]: row["total"] or ZERO
                  for row in taken.values("request_item_key")
                  .annotate(total=Sum("quantity"))}

    out = []
    for row in rows:
        used = contracted.get(row["key"], ZERO)
        out.append({
            **row,
            "contracted": used,
            "remaining": max(row["quantity"] - used, ZERO),
        })
    return out


def _normalize(agreement: Agreement, items: list[dict]) -> list[dict]:
    """Проверить присланные позиции и довести их до записи.

    Позиция из заявки получает наименование и единицу ИЗ ЗАЯВКИ, что бы ни
    прислал клиент: позиция плана — это его строка, а не то, как её
    переписали в форме договора.
    """
    keyed = [item for item in items if item.get("request_item_key")]
    known: dict[str, dict] = {}
    if keyed:
        if agreement.request_id is None:
            raise AgreementItemsViolation(
                "Позиции из заявки есть, а договор ни к какой заявке не привязан — "
                "укажите заявку или впишите позиции вручную")
        known = {row["key"]: row for row in
                 request_items(agreement.request_id, exclude_agreement_id=agreement.pk)}

    seen: set[str] = set()
    out = []
    for item in items:
        key = item.get("request_item_key") or ""
        name = (item.get("name") or "").strip()
        unit = (item.get("unit") or "").strip()
        quantity = Decimal(item["quantity"])
        if key:
            if key in seen:
                raise AgreementItemsViolation(
                    "Одна и та же позиция заявки указана в договоре дважды")
            seen.add(key)
            source = known.get(key)
            if source is None:
                raise AgreementItemsViolation(
                    f"Позиции «{key}» нет в заявке, по которой заключается договор")
            if quantity > source["remaining"]:
                raise AgreementItemsViolation(
                    f"Позиция «{source['name']}»: доступно {_fmt(source['remaining'])}"
                    f"{' ' + source['unit'] if source['unit'] else ''}, "
                    f"в договоре {_fmt(quantity)} — остальное уже законтрактовано "
                    "другими договорами по этой заявке")
            name, unit = source["name"], source["unit"]
        elif not name:
            raise AgreementItemsViolation("Укажите наименование позиции")
        out.append({"request_item_key": key, "name": name, "unit": unit,
                    "quantity": quantity, "amount": item.get("amount")})
    return out


def assert_amounts_match(agreement: Agreement, items: list[dict]) -> None:
    """BR-033: у стандартного договора каждая позиция с суммой, и сумма
    позиций равна сумме договора. У открытого суммы нет — нечего сверять."""
    if not agreement.has_fixed_amount or not items:
        return
    if any(item.get("amount") is None for item in items):
        raise AgreementItemsViolation(
            "Укажите сумму каждой позиции — у стандартного договора она обязательна")
    total = sum((Decimal(item["amount"]) for item in items), ZERO)
    if total != agreement.amount:
        raise AgreementItemsViolation(
            f"Сумма позиций ({total:.2f}) не равна сумме договора "
            f"({agreement.amount:.2f}) — расхождение {abs(total - agreement.amount):.2f}")


def replace_items(agreement: Agreement, items: list[dict]) -> None:
    """Заменить позиции договора присланными (порядок строк — как пришли)."""
    rows = _normalize(agreement, items)
    assert_amounts_match(agreement, rows)
    agreement.items.all().delete()
    AgreementItem.objects.bulk_create([
        AgreementItem(agreement=agreement, line_no=index, **row)
        for index, row in enumerate(rows, start=1)
    ])
    # Договор, загруженный с ``prefetch_related("items")``, помнит СТАРЫЕ
    # позиции — без сброса ответ на правку показал бы то, что только что
    # удалено.
    getattr(agreement, "_prefetched_objects_cache", {}).pop("items", None)


def current_items(agreement: Agreement) -> list[dict]:
    return [{"request_item_key": row.request_item_key, "name": row.name,
             "unit": row.unit, "quantity": row.quantity, "amount": row.amount}
            for row in agreement.items.all()]


#: Обязательны ли позиции для отправки на согласование (ТЗ 9.2: «минимум
#: одна»). ВЫКЛЮЧЕНО, пока в форме договора нет таблицы позиций: без неё
#: договор, заведённый из интерфейса, на согласование было бы не отправить.
#: Включается вместе с формой — одной строкой здесь.
ITEMS_REQUIRED_FOR_APPROVAL = False


def assert_ready_for_approval(agreement: Agreement) -> None:
    """Перед отправкой на согласование: суммы позиций сходятся с договором, и
    количество по заявке всё ещё помещается в остаток — между сохранением
    черновика и отправкой его мог выбрать другой договор. Договор без
    позиций проходит, пока ``ITEMS_REQUIRED_FOR_APPROVAL`` выключен."""
    items = current_items(agreement)
    if not items:
        if ITEMS_REQUIRED_FOR_APPROVAL:
            raise AgreementItemsViolation(
                "В договоре нет ни одной позиции — добавьте позиции перед "
                "отправкой на согласование")
        return
    assert_amounts_match(agreement, items)
    if any(item["request_item_key"] for item in items):
        _normalize(agreement, items)


def serialize_items(agreement: Agreement) -> list[dict]:
    """Позиции для ответа. ``agreement.items.all()`` — чтобы список договоров
    брал их из ``prefetch_related``, а не запросом на строку."""
    return [
        {"id": row.pk, "line_no": row.line_no,
         "request_item_key": row.request_item_key, "name": row.name,
         "unit": row.unit, "quantity": row.quantity, "amount": row.amount}
        for row in agreement.items.all()
    ]


__all__ = [
    "AgreementItemsViolation", "request_items", "replace_items",
    "current_items", "assert_amounts_match", "assert_ready_for_approval",
    "serialize_items",
]
