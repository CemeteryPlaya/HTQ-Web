"""Фоновая сборка экспорта реестра (ТЗ §19, D-32; A2.2, задача 6).

Отдельный файл, а не ``apps/bpp/tasks.py`` (зона B — ночная сверка
«Задействовано»): чтобы задача экспорта не конфликтовала правками в общем
файле, пока обе части пишутся параллельно. ``htqweb/celery.py`` собирает
кроме ``<аппка>.tasks`` ещё и ``<аппка>.tasks_export`` (второй вызов
``autodiscover_tasks(related_name="tasks_export")``); сторож
``apps/core/tests/test_invariants.py`` проверяет задачи обоих модулей
(``_TASK_MODULE_RELATED_NAMES``) — ``require_service`` первой строкой и
``@company_task`` у тенантной аппки.
"""

from __future__ import annotations

from celery import shared_task

from apps.core.services import require_service
from htqweb.tenancy.celery import company_task


@shared_task(name="apps.bpp.tasks_export.build_export")
@company_task
def build_export(*, job_id: str, columns: list[dict], rebuild_path: str,
                 rebuild_kwargs: dict) -> None:
    """Пересобрать выборку (``rebuild_path(**rebuild_kwargs)``), сохранить
    xlsx в ``apps.media_files`` и уведомить заказчика — тело в
    ``services/core/export.py::run_background`` (там же — что при отказе:
    выгрузка помечается ошибкой с причиной, а не падает молча)."""
    require_service("bpp")
    from apps.bpp.services.core import export

    export.run_background(job_id=job_id, columns=columns, rebuild_path=rebuild_path,
                          rebuild_kwargs=rebuild_kwargs)
