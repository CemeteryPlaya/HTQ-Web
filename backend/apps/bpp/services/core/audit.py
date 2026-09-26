"""Журнал изменений документов модуля (ТЗ §25.2).

``record`` пишет строку в той же транзакции, что и изменение: откатилось
изменение — откатилась и запись. Тип объекта — ``app_label.model`` модели
(``bpp.invoice``), ключ — строка UUID.
"""

from __future__ import annotations

from apps.bpp.models import AuditLog


def record(obj, action: str, *, actor_id: int | None, changes: dict | None = None,
           comment: str = "") -> None:
    AuditLog.objects.create(
        object_type=obj._meta.label_lower, object_id=str(obj.pk), action=action,
        actor_id=actor_id, changes=changes or {}, comment=comment or "",
    )


def history(object_type: str, object_id: str) -> list[dict]:
    rows = AuditLog.objects.filter(object_type=object_type, object_id=object_id)
    return [
        {"id": str(row.id), "action": row.action, "actor_id": row.actor_id,
         "changes": row.changes, "comment": row.comment,
         "created_at": row.created_at.isoformat()}
        for row in rows.order_by("created_at")
    ]
