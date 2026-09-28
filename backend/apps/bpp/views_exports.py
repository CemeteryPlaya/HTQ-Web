"""Фоновая выгрузка реестра (ТЗ §19, D-32; A2.2, задача 6).

Один эндпоинт: ``GET /api/bpp/v1/exports/<id>`` — состояние выгрузки, а у
готовой — временная ссылка на файл (``services/core/export.py::download``).
Уведомление о готовности ведёт на экран выгрузки во фронте, и уже он зовёт
эту ручку: переход по ссылке из колокольчика JWT не несёт.

Чужая и несуществующая выгрузка неотличимы намеренно: обе — 404, а не 403,
— подтверждать существование чужой выгрузки незачем. Неверный UUID в адресе
— тоже 404 (``uuid_or_404``), а не 500 от фильтра ORM.
"""

from __future__ import annotations

from htqweb.http import api_view, uuid_or_404

from .services.core import export


@api_view(methods=("GET",), module="bpp", level="read")
def export_download(request, job_id):
    return export.download(request, uuid_or_404(job_id))
