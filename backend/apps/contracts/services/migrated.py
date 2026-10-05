"""«Перенесён в …» на карточках старого раздела (A6.2).

Куда переехала запись ``contracts`` при переносе в модуль БЗО (B6.1),
знает только ``bpp`` — спрашиваем его интерфейс ``migrated_targets``.
Карточке нужна одна цель — документ того же рода: договор переносом
порождает ещё и скрытую техническую заявку (``bpp.purchase_request``),
счёт — тоже; показывать её незачем, её нет ни в одном реестре модуля.

Модуль ``bpp`` выключен (у компании или на платформе) — переноса у этой
компании нет или он недоступен, и подписи «перенесён» нет: это не подмена
значения, а честный ответ «ссылаться некуда», поэтому без ``fallback``.
"""

from __future__ import annotations

from apps.core.services import service_enabled

#: Тип записи ``contracts`` в связях переноса → тип цели, которую показывает карточка.
CARD_TARGETS = {
    "contracts.agreement": "bpp.agreement",
    "contracts.invoice": "bpp.invoice",
    "contracts.counterparty": "bpp.counterparty",
}


def migrated_to(source_type: str, source_id: int) -> list[dict]:
    """``[{target_type, target_id, number}]`` — пусто, если не переносилась."""
    if not service_enabled("bpp"):
        return []
    from apps.bpp import interface as bpp

    target_type = CARD_TARGETS[source_type]
    found = bpp.migrated_targets(source_type, [source_id]).get(str(source_id), [])
    return [row for row in found if row["target_type"] == target_type]
