"""Аппка approvals (домен requests) НЕ производит межаппный интерфейс
(контракт PLAN.md §7): соседи её не вызывают — она сама потребляет
apps.users / apps.hr / apps.messenger.

Модуль-заглушка prep 4.0 оставлен для единообразия скаффолда и как готовая
точка расширения: если появится потребитель, функции добавляются сюда
(каждая — с require_service("approvals") первой строкой), а прямой импорт
apps.approvals.* из другой аппки останется запрещён (test_app_isolation.py).
"""
from __future__ import annotations
