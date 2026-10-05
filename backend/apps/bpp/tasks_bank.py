"""Фоновый разбор загруженной выписки и уборка потерянных разборов (ТЗ
§11.3 п.1–3; план этапа 3 A, задача 3 — A4.1).

Отдельный файл, как ``tasks_export.py``: ``apps/bpp/tasks.py`` — зона B
(ночная сверка «Задействовано»). ``htqweb/celery.py`` собирает и
``<аппка>.tasks_bank`` (``autodiscover_tasks(related_name="tasks_bank")``),
сторож ``apps/core/tests/test_invariants.py`` проверяет его задачи
(``_TASK_MODULE_RELATED_NAMES``).

Первая строка каждой задачи — ``require_service("bpp")``: так сторож
проверяет каждую задачу аппки (сервис аппки — ``bpp``); вторая — рубильник
подмодуля ``bpp_bank``: выключенная загрузка выписок не разбирает и файлы,
уже стоящие в очереди.

Уборка — шаблон «диспетчер + веер» (``htqweb/tenancy/celery.py``), как у
``signoff.retry_no_executor``: beat раз в 10 минут зовёт диспетчер
(расписание — миграция ``bpp/0012_bank_import_reaper_periodic_task``), тот
ставит ``reap_stale_imports`` по каждой действующей компании. До первой
компании (таблицы модуля в ``public``) диспетчер убирает прямо там.
"""

from __future__ import annotations

from celery import shared_task

from apps.core.services import require_service
from htqweb.tenancy.celery import company_dispatch_task, company_task, fan_out_to_companies


@shared_task(name="apps.bpp.tasks_bank.run_bank_import")
@company_task
def run_bank_import(*, import_id: str) -> None:
    """Разобрать выписку загрузки ``import_id`` и записать списания — тело в
    ``services/bank/imports.py::run_import`` (там же — что при отказе:
    загрузка получает статус «Ошибка загрузки» с причиной)."""
    require_service("bpp")
    require_service("bpp_bank")
    from apps.bpp.services.bank import imports

    imports.run_import(import_id)


def _reap() -> dict:
    from apps.bpp.services.bank import imports

    return imports.reap_stale()


@shared_task(name="apps.bpp.tasks_bank.reap_stale_imports")
@company_task
def reap_stale_imports() -> dict:
    """Потерянные разборы компании — в «Ошибка загрузки»
    (``imports.reap_stale``)."""
    require_service("bpp")
    require_service("bpp_bank")
    return _reap()


@shared_task(name="apps.bpp.tasks_bank.reap_stale_imports_dispatch")
@company_dispatch_task
def reap_stale_imports_dispatch() -> dict:
    """Диспетчер: веер ``reap_stale_imports`` по действующим компаниям."""
    require_service("bpp")
    require_service("bpp_bank")
    from apps.companies.interface import active_company_slugs

    if not active_company_slugs():
        return {"public": _reap()}
    return fan_out_to_companies(reap_stale_imports, label="bpp.reap_stale_imports_dispatch")
