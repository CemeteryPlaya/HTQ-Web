"""Ручки альтернативных предложений — подмодуль ``bpp_alternatives`` (ТЗ §12,
A5.1, задача 2): ``/api/bpp/v1/alternatives/…``.

Каждая — под гейтом модуля ``bpp`` с явным уровнем; право «подавать» —
узел ``bpp.alternatives`` create (``offers.create``), авторство и статусы
проверяет сервис. Записывающие ручки идемпотентны (``Idempotency-Key``).
"""

from __future__ import annotations

from htqweb.errors import DomainError
from htqweb.http import api_view, json_error, uuid_or_404

from .schemas import alternatives as schemas
from .services.actor import Actor
from .services.alternatives import offers as service


def _card(request, offer) -> dict:
    return service.serialize(Actor(request), offer)


@api_view(methods=("POST",), module="bpp", level="write", body=schemas.OfferCreate,
          status=201, idempotent=True)
def offer_create(request, data):
    offer = service.create(Actor(request), source_type=data.source_type,
                           source_id=data.source_id)
    return _card(request, offer)


@api_view(methods=("GET",), module="bpp", level="read")
def offer_get(request, offer_id):
    return _card(request, service.get_visible(Actor(request), uuid_or_404(offer_id)))


@api_view(methods=("PATCH",), module="bpp", level="write", body=schemas.OfferUpdate,
          idempotent=True)
def offer_patch(request, offer_id, data):
    sent = data.model_dump(exclude_unset=True)
    version = sent.pop("version", None)
    if sent.get("counterparty_id") is not None:
        sent["counterparty_id"] = str(sent["counterparty_id"])
    offer = service.update_draft(Actor(request), uuid_or_404(offer_id),
                                 expected_version=version, data=sent)
    return _card(request, offer)


@api_view(methods=("DELETE",), module="bpp", level="write", idempotent=True)
def offer_delete(request, offer_id):
    raw = request.GET.get("version")
    if raw and not raw.isdigit():
        raise DomainError("E-VAL-01", "Версия — целое число.",
                          fields=[{"field": "version", "message": "Целое число"}])
    service.delete_draft(Actor(request), uuid_or_404(offer_id),
                         expected_version=int(raw) if raw else None)
    return {"deleted": True}


def offer_detail(request, offer_id):
    if request.method == "GET":
        return offer_get(request, offer_id)
    if request.method == "PATCH":
        return offer_patch(request, offer_id)
    if request.method == "DELETE":
        return offer_delete(request, offer_id)
    return json_error("Method Not Allowed", 405)


@api_view(methods=("POST",), module="bpp", level="write", body=schemas.OfferVersion,
          idempotent=True)
def offer_submit(request, offer_id, data):
    offer = service.submit(Actor(request), uuid_or_404(offer_id), expected_version=data.version)
    return _card(request, offer)


@api_view(methods=("POST",), module="bpp", level="write", body=schemas.OfferVersion,
          idempotent=True)
def offer_withdraw(request, offer_id, data):
    offer = service.withdraw(Actor(request), uuid_or_404(offer_id),
                             expected_version=data.version)
    return _card(request, offer)


@api_view(methods=("POST",), module="bpp", level="write", body=schemas.LimitBody,
          idempotent=True)
def source_limit(request, source_type, source_id, data):
    limit = service.set_limit(Actor(request), source_type=source_type,
                              source_id=uuid_or_404(source_id), limit=data.limit)
    return {"source_type": source_type, "source_id": str(source_id), "alt_limit": limit}
