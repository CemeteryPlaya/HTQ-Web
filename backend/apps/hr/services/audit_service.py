"""Мини-аудит-сервис — порт services/hr/app/services/audit_service.py +
GET /logs/ (services/hr/app/api/v1/audit.py — роутер смонтирован под
``prefix="/logs"``, "audit" осталось только в имени файла/модели).

``log(...)`` — единственный метод, который реально зовёт
``employee_service``. Не обёрнут в try/except нигде в исходнике (вызов
``audit.log(...)`` — обычный await посреди мутации): сбой записи аудита
обязан уронить всю мутацию целиком, ровно как в исходнике — не подавляем
исключение здесь.

``list_logs``/``serialize`` — порт list-comprehension в хвосте
``get_audit_log`` роутера исходника: голый список dict (НЕ пагинационный
конверт ``{"items": …}``, в отличие от большинства других list-эндпойнтов
этого домена).
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


def serialize(log: AuditLog) -> dict:
    return {
        "id": log.id,
        "entity_type": log.entity_type,
        "entity_id": log.entity_id,
        "action": log.action,
        "old_values": log.old_values,
        "new_values": log.new_values,
        "changed_by": log.changed_by,
        "ip_address": log.ip_address,
        "created_at": log.created_at.isoformat() if log.created_at else None,
    }


def list_logs(
    *,
    entity_type: str | None = None,
    entity_id: int | None = None,
    page: int = 1,
    limit: int = 50,
) -> list[dict]:
    qs = AuditLog.objects.all()
    if entity_type:
        qs = qs.filter(entity_type=entity_type)
    if entity_id is not None:
        qs = qs.filter(entity_id=entity_id)

    offset = (page - 1) * limit
    qs = qs.order_by("-created_at")[offset : offset + limit]
    return [serialize(log) for log in qs]
