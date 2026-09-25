"""Сравнительная таблица поставщиков: расчёт итогов и проверка заполнения.

Закупщик сводит предложения в таблицу — строки берутся из позиций заявки,
колонки он добавляет сам. Отсюда два действия, которые нельзя оставить
интерфейсу:

* **вывести итог** выбранного предложения в значение виджета (``total``,
  ``supplier_name``). Считает сервер, потому что по этому числу дальше
  утверждают деньги: сумма заявки, сверка со счётом, личная аналитика — всё
  берёт ``<ключ>.total``, и он обязан быть посчитан одинаково, кто бы ни
  прислал значение;
* **сказать, чего не хватает**, чтобы закрыть шаг: движок спрашивает
  ``approval_hooks._check_requirement``, а тот — эту функцию.

Цена в клетке — ЗА ЕДИНИЦУ (так подписана колонка и в исходной СТ), итог по
поставщику = Σ цена × количество из позиции. Нет колонки количества —
считаем по одной единице на строку.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

# Сколько поставщиков помещается в таблицу. Ограничение не выдумано «для
# ровного счёта»: колонки рисуются рядом, и после десятка таблица перестаёт
# читаться — а сравнивать глазами её и заводили.
MAX_SUPPLIERS = 10


def derive(schema, values: dict[str, Any]) -> dict[str, Any]:
    """Дописать в значения выведенные поля каждой таблицы поставщиков.

    Возвращает НОВЫЙ словарь: вызывается там же, где значения сохраняются,
    и молча править переданное не должен.
    """
    out = dict(values)
    for field in schema.fields:
        if field.type != "supplier_quotes":
            continue
        value = out.get(field.key)
        if not isinstance(value, dict):
            continue
        quantities = _quantities(field, out)
        suppliers = [s for s in (value.get("suppliers") or [])
                     if isinstance(s, dict)]
        totals = [_total_of(s, quantities) for s in suppliers]
        chosen = _chosen_index(value, suppliers)
        out[field.key] = {
            **value,
            # Итоги по каждому поставщику — чтобы карточка и таблица данных
            # показывали их без повторения той же арифметики.
            "totals": [str(t) for t in totals],
            "total": str(totals[chosen]) if chosen is not None else "",
            "supplier_name": (str(suppliers[chosen].get("name") or "").strip()
                              if chosen is not None else ""),
        }
    return out


def problem(schema, values: dict[str, Any], field_key: str) -> str | None:
    """Чего не хватает в таблице ``field_key``, чтобы закрыть шаг, — текст
    для человека или ``None``.

    Минимум — ОДНО предложение: сколько собирать, решает закупщик, и
    заставлять его выдумывать третьего поставщика на товар, который возят
    двое, система не вправе. А вот отметить выбранного обязана: без этого
    неизвестна сумма, которую утверждает CFO.
    """
    field = next((f for f in schema.fields
                  if f.key == field_key and f.type == "supplier_quotes"), None)
    if field is None:
        return None
    value = values.get(field_key)
    suppliers = [s for s in ((value or {}).get("suppliers") or [])
                 if isinstance(s, dict)] if isinstance(value, dict) else []
    named = [s for s in suppliers if str(s.get("name") or "").strip()]
    if not named:
        return f"добавить в «{field.label}» хотя бы одно предложение поставщика"
    if len(suppliers) > MAX_SUPPLIERS:
        return (f"в «{field.label}» слишком много поставщиков "
                f"(максимум {MAX_SUPPLIERS})")

    rows = len(_quantities(field, values))
    for supplier in named:
        prices = supplier.get("prices") or []
        missing = [i for i in range(rows) if _decimal(_at(prices, i)) is None]
        if missing:
            name = str(supplier.get("name")).strip()
            return (f"заполнить цены у поставщика «{name}» "
                    f"({len(missing)} из {rows} позиций пусты)")

    if _chosen_index(value, suppliers) is None:
        return f"отметить выбранного поставщика в «{field.label}»"
    return None


# ── внутреннее ────────────────────────────────────────────────────────

def _quantities(field, values: dict[str, Any]) -> list[Decimal]:
    """Количества позиций заявки — по одному на строку таблицы."""
    rows = values.get(field.items_field) or []
    out = []
    for row in rows:
        if not isinstance(row, dict):
            out.append(Decimal(1))
            continue
        raw = row.get(field.quantity_key) if field.quantity_key else None
        out.append(_decimal(raw) or Decimal(1))
    return out


def _total_of(supplier: dict, quantities: list[Decimal]) -> Decimal:
    prices = supplier.get("prices") or []
    total = Decimal(0)
    for index, quantity in enumerate(quantities):
        price = _decimal(_at(prices, index))
        if price is not None:
            total += price * quantity
    return total


def _chosen_index(value: Any, suppliers: list[dict]) -> int | None:
    """Индекс выбранного поставщика; ``None``, если не выбран или указан
    несуществующий (колонку могли удалить после выбора)."""
    if not isinstance(value, dict):
        return None
    raw = value.get("chosen")
    try:
        index = int(raw)
    except (TypeError, ValueError):
        return None
    if 0 <= index < len(suppliers) and str(suppliers[index].get("name") or "").strip():
        return index
    return None


def _at(values: list, index: int) -> Any:
    return values[index] if 0 <= index < len(values) else None


def _decimal(raw: Any) -> Decimal | None:
    if raw is None or raw == "":
        return None
    try:
        return Decimal(str(raw))
    except (InvalidOperation, ValueError):
        return None
