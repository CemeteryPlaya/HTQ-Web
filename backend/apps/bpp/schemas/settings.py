"""Тело правки параметра модуля (``PATCH /api/bpp/v1/settings/<ключ>``).

Схема не проверяет даже тип: вид значения задаёт параметр реестра
(``services/core/settings.EDITABLE``), и отказ приходит кодом модуля
E-VAL-01 с полем ``value``, а не общей ошибкой схемы.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class SettingUpdate(BaseModel):
    value: Any = None
