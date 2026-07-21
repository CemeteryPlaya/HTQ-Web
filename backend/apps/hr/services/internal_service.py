"""S2S internal endpoint — порт services/hr/app/api/v1/internal.py.

Единственный эндпойнт (``GET /internal/supervisor?user_id=…``), которым
requests-service (в этом монолите — будущий apps.approvals) резолвит
``initiator_supervisor``/``department_head`` для workflow-назначений.

Резолюция руководителя буквально переиспользует
``employee_card_service._resolve_manager`` (уже перенесённую под-модулем
employee_card) — не дублируется здесь.
"""
from __future__ import annotations

from apps.hr.models import Employee
from apps.hr.services import employee_card_service as card_svc


def get_supervisor_user_id(user_id: int) -> int | None:
    """Возвращает user_id руководителя отдела ``user_id``-сотрудника.

    Если сотрудник сам руководит своим отделом, поднимается по ltree-path
    вверх до ближайшего родительского отдела с ДРУГИМ руководителем.
    ``None``, если сотрудник не найден или руководитель не резолвится (нет
    отдела, нет вышестоящего руководителя) — буквальный порт докстринга
    исходника.
    """
    emp = (
        Employee.objects.select_related("department")
        .filter(user_id=user_id, is_deleted=False)
        .first()
    )
    if emp is None:
        return None
    manager = card_svc._resolve_manager(emp)
    return manager.user_id if manager is not None else None
