# Celery-задачи домена hr. Каждая — @shared_task с require_service("hr")
# первой строкой (мета-тест Test 1).
"""Периодические задачи hr.

``sync_identity`` — ночная сверка кадровой копии идентичности с аккаунтами
(спека docs/superpowers/specs/2026-08-25-hr-identity-sync-design.md §8).

hr — tenant-аппка (``settings.TENANT_APPS``): таблицы Employee живут в схеме
компании, а не в public. У задачи Celery нет HTTP-запроса, значит контекста
компании нет тоже — ``sync_identity`` помечена ``@company_task`` и получает
``company_slug`` именованным аргументом (``htqweb/tenancy/celery.py``).
Beat планирует не её, а диспетчера ``sync_identity_dispatch`` без компании:
тот веером ставит ``sync_identity`` на каждую действующую компанию
(``fan_out_to_companies``) — см. docs/multi-company-tenancy-followups.md п.1.
"""
from __future__ import annotations

import logging

from celery import shared_task

from apps.core.services import require_service
from htqweb.tenancy.celery import company_dispatch_task, company_task, fan_out_to_companies

logger = logging.getLogger(__name__)


@shared_task(name="apps.hr.tasks.sync_identity")
@company_task
def sync_identity() -> dict:
    """Привести копии идентичности в соответствие с аккаунтами.

    Расхождение здесь означает, что в копию писали мимо API (django-admin,
    SQL, импорт): найденное кадровое значение оформляется заявкой, копия
    восстанавливается, подтверждающий получает уведомление. Молчаливой
    перезаписи нет — см. ``identity_sync_service.reconcile_employee``.

    Уволенные и не связанные с аккаунтом пропускаются: у первых копия уже
    неактуальна по определению, у вторых нет владельца.

    Вызывается как ``sync_identity.delay(company_slug="...")`` —
    ``@company_task`` разворачивает именованный аргумент в контекст компании
    ДО вызова тела и не передаёт его дальше (см. докстринг
    ``htqweb/tenancy/celery.py``), поэтому здесь читаем компанию из
    контекста, а не из параметра.
    """
    require_service("hr")
    from apps.hr.models import Employee, EmployeeStatus
    from apps.hr.services import identity_sync_service
    from htqweb.tenancy.context import current_company

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

    logger.info("hr.sync_identity company=%s checked=%s requests=%s",
                current_company(), len(employee_ids), requests)
    return {"checked": len(employee_ids), "requests": requests}


@shared_task(name="apps.hr.tasks.sync_identity_dispatch")
@company_dispatch_task
def sync_identity_dispatch() -> dict:
    """Диспетчер: веер ``sync_identity`` по каждой действующей компании.

    Сама задача — без компании: только читает
    ``apps.companies.interface.active_company_slugs()`` и ставит по одной
    ``sync_identity`` на компанию, передавая ``company_slug`` именованным
    аргументом. Сбой постановки для одной компании не отменяет остальные
    (``fan_out_to_companies`` ловит исключение на каждой компании отдельно).
    Это задача, на которую переведено расписание beat — см. миграцию
    ``apps/hr/migrations/0020_sync_identity_dispatch_periodic_task.py``.
    """
    require_service("hr")
    return fan_out_to_companies(sync_identity, label="hr.sync_identity_dispatch")
