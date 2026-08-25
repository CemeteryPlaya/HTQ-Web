# Celery-задачи домена hr. Каждая — @shared_task с require_service("hr")
# первой строкой (мета-тест Test 1).
"""Периодические задачи hr.

``sync_identity`` — ночная сверка кадровой копии идентичности с аккаунтами
(спека docs/superpowers/specs/2026-08-25-hr-identity-sync-design.md §8).
"""
from __future__ import annotations

import logging

from celery import shared_task

from apps.core.services import require_service

logger = logging.getLogger(__name__)


@shared_task(name="apps.hr.tasks.sync_identity")
def sync_identity() -> dict:
    """Привести копии идентичности в соответствие с аккаунтами.

    Расхождение здесь означает, что в копию писали мимо API (django-admin,
    SQL, импорт): найденное кадровое значение оформляется заявкой, копия
    восстанавливается, подтверждающий получает уведомление. Молчаливой
    перезаписи нет — см. ``identity_sync_service.reconcile_employee``.

    Уволенные и не связанные с аккаунтом пропускаются: у первых копия уже
    неактуальна по определению, у вторых нет владельца.
    """
    require_service("hr")
    from apps.hr.models import Employee, EmployeeStatus
    from apps.hr.services import identity_sync_service

    employee_ids = list(
        Employee.objects
        .filter(is_deleted=False, user_id__isnull=False)
        .exclude(status=EmployeeStatus.TERMINATED)
        .values_list("id", flat=True)
    )

    requests = 0
    for employee_id in employee_ids:
        if identity_sync_service.reconcile_employee(employee_id) is not None:
            requests += 1

    logger.info("hr.sync_identity checked=%s requests=%s",
                len(employee_ids), requests)
    return {"checked": len(employee_ids), "requests": requests}
