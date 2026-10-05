"""Настройки модуля БЗО в схеме компании (``ModuleSetting``).

Умолчания — здесь, в коде: строка в таблице появляется, только когда
настройку поменяли, и её смена пишется в журнал (ТЗ §25.2).

Не всякая строка таблицы — параметр для человека. Правке с экрана
«Настройки» открыты только ключи реестра ``EDITABLE``; служебные строки
(итог ночной сверки «Задействовано» ``committed_check_last`` — его пишет
сам модуль) ручки не показывают и не принимают: для них такого ключа нет.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.db import transaction

from apps.bpp.models.settings import ModuleSetting
from apps.bpp.services.core import audit
from htqweb.errors import DomainError

__all__ = ["DEFAULTS", "EDITABLE", "Param", "get_setting", "list_params", "set_setting",
           "update_param"]

#: Умолчания настроек модуля.
DEFAULTS: dict[str, object] = {
    # Метка «Проверенный» у контрагента — после стольких удачных документов:
    # договор «Действует»/«Исполнен» или счёт «Оплачено» (D-20, Q-E23).
    "counterparty_verified_threshold": 3,
}

_AUDIT_TYPE = "bpp.modulesetting"


@dataclass(frozen=True)
class Param:
    """Параметр модуля, открытый правке АДМ на экране «Настройки».

    ``kind`` — вид значения и правило проверки; пока только ``integer``
    (целое в границах ``min``…``max`` включительно).
    """

    key: str
    label: str
    kind: str
    min: int | None = None
    max: int | None = None
    help: str = ""


#: Реестр параметров для правки. Ключа нет в реестре — ручки отвечают 404,
#: как на несуществующий: служебную строку руками не поправить.
EDITABLE: dict[str, Param] = {param.key: param for param in (
    Param(
        key="counterparty_verified_threshold",
        label="Порог метки «Проверенный» контрагента, удачных документов",
        kind="integer", min=1, max=100,
        help=("Контрагент получает метку «Проверенный» после стольких удачных "
              "документов: договор «Действует» или «Исполнен», счёт «Оплачено». "
              "Ручное решение ФД в карточке контрагента порог перебивает."),
    ),
)}


def get_setting(key: str, default=None):
    """Значение настройки; строки нет — ``default``, а без него — умолчание
    модуля (``DEFAULTS``)."""
    row = ModuleSetting.objects.filter(pk=key).first()
    if row is not None:
        return row.value
    return default if default is not None else DEFAULTS.get(key)


@transaction.atomic
def set_setting(key: str, value, *, actor_id: int | None) -> None:
    # «Было» — под блокировкой строки: две одновременные правки иначе обе
    # записали бы в неизменяемый журнал одно и то же старое значение.
    row = ModuleSetting.objects.select_for_update().filter(pk=key).first()
    before = row.value if row is not None else DEFAULTS.get(key)
    ModuleSetting.objects.update_or_create(
        key=key, defaults={"value": value, "updated_by": actor_id})
    audit.record_for(_AUDIT_TYPE, key, "updated", actor_id=actor_id,
                     changes={"value": [before, value]})


# ── параметры для экрана «Настройки» ────────────────────────────────────

def _serialize(param: Param, row: ModuleSetting | None) -> dict:
    return {
        "key": param.key,
        "label": param.label,
        "value": row.value if row is not None else DEFAULTS.get(param.key),
        "default": DEFAULTS.get(param.key),
        "kind": param.kind,
        "min": param.min,
        "max": param.max,
        "help": param.help,
        "updated_at": row.updated_at.isoformat() if row is not None and row.updated_at else None,
    }


def _editable(key: str) -> Param:
    param = EDITABLE.get(key)
    if param is None:
        raise DomainError("E-NOT-FOUND", "Параметр модуля не найден.", status=404)
    return param


def _clean(param: Param, value):
    """Проверенное значение параметра; неверное — E-VAL-01 с полем ``value``."""
    if param.kind == "integer":
        # bool — подкласс int в Python: true из JSON числом не считается.
        ok = isinstance(value, int) and not isinstance(value, bool)
        if ok and param.min is not None and value < param.min:
            ok = False
        if ok and param.max is not None and value > param.max:
            ok = False
        if not ok:
            bounds = " ".join(part for part in (
                f"от {param.min}" if param.min is not None else "",
                f"до {param.max}" if param.max is not None else "") if part)
            message = f"{param.label}: целое число{' ' + bounds if bounds else ''}."
            raise DomainError("E-VAL-01", message,
                              fields=[{"field": "value", "message": message}])
        return value
    raise AssertionError(f"вид параметра {param.kind!r} не поддержан")  # pragma: no cover


def list_params() -> list[dict]:
    """Параметры реестра в его порядке: значение из таблицы, а строки нет —
    умолчание модуля."""
    rows = {row.key: row for row in ModuleSetting.objects.filter(pk__in=list(EDITABLE))}
    return [_serialize(param, rows.get(key)) for key, param in EDITABLE.items()]


@transaction.atomic
def update_param(key: str, value, *, actor_id: int | None) -> dict:
    """Сменить параметр реестра: проверка, запись через ``set_setting``
    (журнал). То же значение — без записи и без строки журнала."""
    param = _editable(key)
    clean = _clean(param, value)
    if clean != get_setting(key):
        set_setting(key, clean, actor_id=actor_id)
    return _serialize(param, ModuleSetting.objects.filter(pk=key).first())
