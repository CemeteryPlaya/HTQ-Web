"""Celery-задачи модуля БЗО.

Шаблон «диспетчер + веер» (``htqweb/tenancy/celery.py``): ``bpp`` —
тенантная аппка, у периодической задачи своей компании нет. До первой
компании (таблицы модуля ещё в ``public``) диспетчер работает прямо там.
"""

from __future__ import annotations

from celery import shared_task

from apps.core.services import require_service
from htqweb.tenancy.celery import company_dispatch_task, company_task, fan_out_to_companies


def _check() -> dict:
    from apps.bpp.services.budget import check

    return check.run()


@shared_task(name="apps.bpp.tasks.committed_check")
@company_task
def committed_check() -> dict:
    """Ночная сверка «Задействовано» одной компании (B2.4)."""
    require_service("bpp")
    return _check()


@shared_task(name="apps.bpp.tasks.committed_check_dispatch")
@company_dispatch_task
def committed_check_dispatch() -> dict:
    """Диспетчер: веер ``committed_check`` по действующим компаниям."""
    require_service("bpp")
    from apps.companies.interface import active_company_slugs

    if not active_company_slugs():
        return {"public": _check()}
    return fan_out_to_companies(committed_check, label="bpp.committed_check_dispatch")
