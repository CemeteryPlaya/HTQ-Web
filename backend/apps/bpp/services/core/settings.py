"""Настройки модуля БЗО в схеме компании (``ModuleSetting``).

Умолчания — здесь, в коде: строка в таблице появляется, только когда
настройку поменяли, и её смена пишется в журнал (ТЗ §25.2).
"""

from __future__ import annotations

from django.db import transaction

from apps.bpp.models.settings import ModuleSetting
from apps.bpp.services.core import audit

__all__ = ["DEFAULTS", "get_setting", "set_setting"]

#: Умолчания настроек модуля.
DEFAULTS: dict[str, object] = {
    # Метка «Проверенный» у контрагента — после стольких удачных документов:
    # договор «Действует»/«Исполнен» или счёт «Оплачено» (D-20, Q-E23).
    "counterparty_verified_threshold": 3,
}

_AUDIT_TYPE = "bpp.modulesetting"


def get_setting(key: str, default=None):
    """Значение настройки; строки нет — ``default``, а без него — умолчание
    модуля (``DEFAULTS``)."""
    row = ModuleSetting.objects.filter(pk=key).first()
    if row is not None:
        return row.value
    return default if default is not None else DEFAULTS.get(key)


@transaction.atomic
def set_setting(key: str, value, *, actor_id: int | None) -> None:
    before = get_setting(key)
    ModuleSetting.objects.update_or_create(
        key=key, defaults={"value": value, "updated_by": actor_id})
    audit.record_for(_AUDIT_TYPE, key, "updated", actor_id=actor_id,
                     changes={"value": [before, value]})
