"""Мини-аудит-сервис — порт services/hr/app/services/audit_service.py.

Только ``log(...)`` — единственный метод, который реально зовёт
``employee_service``. Не обёрнут в try/except нигде в исходнике (вызов
``audit.log(...)`` — обычный await посреди мутации): сбой записи аудита
обязан уронить всю мутацию целиком, ровно как в исходнике — не подавляем
исключение здесь.
"""
from __future__ import annotations

from apps.hr.models import AuditLog


def log(
    *,
    entity_type: str,
    entity_id: int,
    action: str,
    changed_by: int,
    old_values: dict | None = None,
    new_values: dict | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> AuditLog:
    return AuditLog.objects.create(
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        old_values=old_values,
        new_values=new_values,
        changed_by=changed_by,
        ip_address=ip_address,
        user_agent=user_agent,
    )
