"""Публичный API аппки access для ДРУГИХ аппок.

Единственный способ, которым сосед имеет право обращаться к правам. Прямой
импорт ``apps.access.models`` / ``apps.access.services`` из другой аппки
запрещён и ловится ``apps/core/tests/test_app_isolation.py``.

Наполняется в задаче 4 плана (``permission_level``, ``permissions_for``) и
задаче 5 (``subordinate_companies``).
"""

from __future__ import annotations

__all__: list[str] = []
