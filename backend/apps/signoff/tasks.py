"""Celery-задачи signoff: повторный поиск исполнителей (мастер-план БЗО, B1.2).

Этап ленивого маршрута, у роли которого не оказалось исполнителя, ждёт в
состоянии «Нет исполнителя» (ТЗ §16.1 п.5). Назначили сотрудника или
временного исполнителя должности — эта периодика находит его и оживляет
этап; ручка ``POST processes/<id>/retry-executors`` делает то же по одному
процессу без ожидания.

Шаблон «диспетчер + веер» (``htqweb/tenancy/celery.py``): signoff —
тенантная аппка, у задачи своей компании нет. До первой компании (схем ещё
нет, таблицы signoff в ``public``) диспетчер работает прямо в ``public`` —
иначе на стенде без компаний этапы не оживали бы никогда.
"""

from __future__ import annotations

import logging

from celery import shared_task

from apps.core.services import require_service
from htqweb.tenancy.celery import company_dispatch_task, company_task, fan_out_to_companies

logger = logging.getLogger(__name__)


def _retry_all() -> dict:
    from apps.signoff.services import engine

    process_ids = engine.pending_no_executor_process_ids()
    found = sum(engine.retry_no_executor(process_id) for process_id in process_ids)
    return {"processes": len(process_ids), "found": found}


@shared_task(name="apps.signoff.tasks.retry_no_executor")
@company_task
def retry_no_executor() -> dict:
    """Повторный поиск исполнителей по всем ждущим процессам компании."""
    require_service("signoff")
    return _retry_all()


@shared_task(name="apps.signoff.tasks.retry_no_executor_dispatch")
@company_dispatch_task
def retry_no_executor_dispatch() -> dict:
    """Диспетчер: веер ``retry_no_executor`` по действующим компаниям."""
    require_service("signoff")
    from apps.companies.interface import active_company_slugs

    if not active_company_slugs():
        return {"public": _retry_all()}
    return fan_out_to_companies(retry_no_executor, label="signoff.retry_no_executor_dispatch")
