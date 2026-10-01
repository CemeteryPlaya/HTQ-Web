"""Ручки альтернативных предложений — подмодуль ``bpp_alternatives`` (ТЗ §12,
A5.1, задачи 2 и 4): ``/api/bpp/v1/alternatives/…``.

Каждая — под гейтом модуля ``bpp`` с явным уровнем; право «подавать» —
узел ``bpp.alternatives`` create (``offers.create``), авторство и статусы
проверяет сервис. Записывающие ручки идемпотентны (``Idempotency-Key``).
Лента L-09, сравнение и «Мои альтернативы» — ``services/alternatives/read.py``
(право ``bpp.alternatives`` view, иначе 403); неверный параметр — 422
``E-VAL-01`` на своём поле, а не пустой список.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation

from htqweb.errors import DomainError
from htqweb.http import api_view, json_error, uuid_or_404

from .models import OfferStatus
from .schemas import alternatives as schemas
from .services.actor import Actor
from .services.alternatives import offers as service
from .services.alternatives import read
from .services.budget.read import uuid_param
from .services.params import int_param

_YES, _NO = ("1", "true", "yes"), ("0", "false", "no")


def _card(request, offer) -> dict:
    return read.card(Actor(request), offer)


def _bad(name: str, message: str) -> DomainError:
    return DomainError("E-VAL-01", message, fields=[{"field": name, "message": message}])


def _flag(params, name: str) -> bool | None:
    raw = (params.get(name) or "").strip().lower()
    if not raw:
        return None
    if raw in _YES:
        return True
    if raw in _NO:
        return False
    raise _bad(name, "Признак — yes или no (1 или 0).")


def _date(params, name: str) -> date | None:
    raw = params.get(name) or None
    if raw is None:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        raise _bad(name, "Дата — в формате ГГГГ-ММ-ДД.") from None


def _amount(params, name: str) -> Decimal | None:
    raw = (params.get(name) or "").strip().replace(" ", "").replace(",", ".")
    if not raw:
        return None
    try:
        value = Decimal(raw)
    except InvalidOperation:
        raise _bad(name, "Сумма — число.") from None
    if not value.is_finite():
        raise _bad(name, "Сумма — число.")
    return value


def _uuids(request, name: str) -> list[str]:
    return [uuid_param(value, name) for value in request.GET.getlist(name) if value]


def _source(params) -> tuple[str, str] | None:
    raw = params.get("source") or None
    if raw is None:
        return None
    kind, _, key = raw.partition(":")
    if kind not in read.KINDS:
        raise _bad("source", "Документ — invoice:<id> или agreement:<id>.")
    return kind, uuid_param(key, "source")


def _feed_filters(request) -> read.FeedFilters:
    params = request.GET
    kind = params.get("kind") or None
    if kind is not None and kind not in read.KINDS:
        raise _bad("kind", "Вид — invoice или agreement.")
    counterparty = params.get("counterparty_id") or None
    sent_from, sent_to = _date(params, "sent_from"), _date(params, "sent_to")
    if sent_from and sent_to and sent_from > sent_to:
        raise _bad("sent_to", "Дата «по» раньше даты «с».")
    q = (params.get("q") or "").strip()
    if len(q) > 200:
        raise _bad("q", "Не длиннее 200 символов.")
    return read.FeedFilters(
        kind=kind, author_id=int_param(params, "author_id"),
        project_ids=_uuids(request, "project_id"), article_ids=_uuids(request, "article_id"),
        counterparty_id=uuid_param(counterparty, "counterparty_id") if counterparty else None,
        q=q or None, amount_from=_amount(params, "amount_from"),
        amount_to=_amount(params, "amount_to"), sent_from=sent_from, sent_to=sent_to,
        without_offers=bool(_flag(params, "without_offers")), mine=_flag(params, "mine"),
        source=_source(params))


@api_view(methods=("GET",), module="bpp", level="read")
def feed(request):
    params = request.GET
    return read.feed(Actor(request), _feed_filters(request),
                     page=int_param(params, "page", 1, minimum=1),
                     page_size=int_param(params, "page_size", 50))


@api_view(methods=("GET",), module="bpp", level="read")
def source_comparison(request, source_type, source_id):
    return read.comparison(Actor(request), source_type, uuid_or_404(source_id))


@api_view(methods=("GET",), module="bpp", level="read")
def offer_list(request):
    """«Мои альтернативы»: ``?mine=1&status=`` (статус повторяемый)."""
    params = request.GET
    if _flag(params, "mine") is False:
        raise _bad("mine", "Список — только ваших альтернатив: mine=1.")
    statuses = [value for value in params.getlist("status") if value]
    unknown = [value for value in statuses if value not in OfferStatus.values]
    if unknown:
        raise _bad("status", "Допустимо: " + ", ".join(OfferStatus.values))
    return read.my_offers(Actor(request), statuses=statuses,
                          page=int_param(params, "page", 1, minimum=1),
                          page_size=int_param(params, "page_size", 50))


@api_view(methods=("POST",), module="bpp", level="write", body=schemas.OfferCreate,
          status=201, idempotent=True)
def offer_create(request, data):
    offer = service.create(Actor(request), source_type=data.source_type,
                           source_id=data.source_id)
    return _card(request, offer)


def offers_collection(request):
    if request.method == "GET":
        return offer_list(request)
    if request.method == "POST":
        return offer_create(request)
    return json_error("Method Not Allowed", 405)


@api_view(methods=("GET",), module="bpp", level="read")
def offer_get(request, offer_id):
    return _card(request, read.get_visible(Actor(request), uuid_or_404(offer_id)))


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
