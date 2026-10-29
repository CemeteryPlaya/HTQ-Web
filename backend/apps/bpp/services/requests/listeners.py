"""Слушатели смены статуса ЗЗ тендерного модуля (T1.2, мастер-план tender T-09).

Приём — как у ``project.interface.register_change_listener``: БЗО не знает
про tender, только про реестр подписчиков. Сосед подписывается из своего
``ready()`` через ``bpp.interface.register_request_listener``. Слушатель
зовётся в транзакции смены статуса и только для ЗЗ с ``source="tender"``;
его исключение откатывает и саму смену статуса.

Модуль ничего не импортирует из сервисов заявки — те зовут ``changed``
из своих переходов и колбэков согласования.
"""

from __future__ import annotations

from apps.bpp.models import PurchaseRequest, RequestSource

#: Подписчики ``fn(RequestStatusOut) -> None``.
_LISTENERS: list = []


def add(listener) -> None:
    if listener not in _LISTENERS:
        _LISTENERS.append(listener)


def status_out(req: PurchaseRequest):
    """Статус ЗЗ для tender — ``RequestStatusOut``."""
    from apps.bpp.schemas.tender import RequestStatusOut

    return RequestStatusOut(bpp_request_id=str(req.pk), number=req.number,
                            status=req.status, status_comment=req.status_comment,
                            rework_comment=req.rework_comment)


def changed(request_id) -> None:
    """Сообщить подписчикам о смене статуса ЗЗ — в той же транзакции.
    Заявки БЗО без ``source="tender"`` подписчикам не видны."""
    if not _LISTENERS:
        return
    req = (PurchaseRequest.objects.filter(pk=request_id, source=RequestSource.TENDER)
           .only("id", "number", "status", "status_comment", "rework_comment").first())
    if req is None:
        return
    snapshot = status_out(req)
    for listener in list(_LISTENERS):
        listener(snapshot)
