"""Журнал изменений документов модуля (ТЗ §25.2).

``record`` пишет строку в той же транзакции, что и изменение: откатилось
изменение — откатилась и запись. Тип объекта — ``app_label.model`` модели
(``bpp.invoice``), ключ — строка UUID.

Чтение журнала через ручку ``history/<тип>/<id>`` требует ПРОВЕРКИ ДОСТУПА к
самому объекту: в ``changes`` лежат суммы и контрагенты, и уровня модуля
``bpp:read`` для этого мало. Каждый тип документа регистрирует свою проверку
(``register_history_access``) — там же, где объявляет модель. Тип без
проверки не читается никем: забытая регистрация закрывает журнал, а не
открывает.
"""

from __future__ import annotations

from typing import Callable

from apps.bpp.models import AuditLog

#: object_type → ``can_view(request, object_id) -> bool``.
_HISTORY_ACCESS: dict[str, Callable[[object, str], bool]] = {}


def register_history_access(object_type: str, can_view: Callable[[object, str], bool]) -> None:
    """Разрешить чтение журнала объектов типа ``object_type`` тем, кому
    ``can_view(request, object_id)`` отвечает ``True`` (права и
    принадлежность — как у карточки самого документа)."""
    _HISTORY_ACCESS[object_type] = can_view


def can_view_history(request, object_type: str, object_id: str) -> bool:
    can_view = _HISTORY_ACCESS.get(object_type)
    return bool(can_view and can_view(request, object_id))


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
