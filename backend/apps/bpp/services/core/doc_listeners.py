"""Смена статуса счёта и договора — одна точка для соседей (пакет B-2, тендер
T5.3).

``status_changed(doc_type, doc_id)`` зовётся на каждой смене статуса документа
(там, где раньше звался только ``kpi.sync_for_document``) и на переходах
закрывающих документов: сперва KPI снабжения (A5.2, идемпотентно), затем
слушатели ``register_document_listener`` — в той же транзакции, как слушатели
заявки (``requests/listeners``). Слушателю приходят только документы из
тендера (непустой ``tender_key``): БЗО не знает про tender, только про реестр.
"""

from __future__ import annotations

from collections.abc import Callable

from apps.bpp.services.alternatives import kpi

_LISTENERS: list[Callable] = []


def register(fn: Callable) -> None:
    if fn not in _LISTENERS:
        _LISTENERS.append(fn)


def status_changed(doc_type: str, doc_id) -> None:
    kpi.sync_for_document(doc_type, doc_id)
    if not _LISTENERS:
        return
    from apps.bpp.services.requests import tender_documents

    out = tender_documents.status_of_id(doc_type, doc_id)
    if out is None:
        return
    for fn in list(_LISTENERS):
        fn(out)
