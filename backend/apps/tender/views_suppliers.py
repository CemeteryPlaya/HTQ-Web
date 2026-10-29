"""Ручки справочников участников: контакты контрагентов, потенциальные
поставщики, поиск контрагентов БЗО (T2.2; план этапов 0–2, §4.3).

Каждая — под гейтом модуля ``tender`` с явным уровнем; узел
``tender.prospects`` (для поиска контрагентов — ``tender.tenders``) проверяет
сервис.
"""

from __future__ import annotations

from apps.bpp import interface as bpp
from htqweb.http import api_view, json_error

from . import schemas
from .services.suppliers import contacts, prospects
from .services.tenders.ctx import Ctx

SEARCH_LIMIT = 20


# ── контакты ────────────────────────────────────────────────────────────

@api_view(methods=("GET",), module="tender", level="read")
def contact_list(request):
    return contacts.list_contacts(Ctx.from_request(request),
                                  request.GET.get("counterparty_id") or None)


@api_view(methods=("POST",), module="tender", level="write", body=schemas.ContactIn,
          status=201, idempotent=True)
def contact_create(request, data):
    return contacts.create(Ctx.from_request(request), data.model_dump())


def contacts_collection(request):
    if request.method == "GET":
        return contact_list(request)
    if request.method == "POST":
        return contact_create(request)
    return json_error("Method Not Allowed", 405)


@api_view(methods=("PATCH",), module="tender", level="write", body=schemas.ContactUpdate,
          idempotent=True)
def contact_patch(request, contact_id, data):
    return contacts.update(Ctx.from_request(request), contact_id,
                           data.model_dump(exclude_unset=True))


@api_view(methods=("DELETE",), module="tender", level="write", idempotent=True)
def contact_delete(request, contact_id):
    contacts.delete(Ctx.from_request(request), contact_id)
    return {"deleted": True}


def contact_detail(request, contact_id):
    if request.method == "PATCH":
        return contact_patch(request, contact_id)
    if request.method == "DELETE":
        return contact_delete(request, contact_id)
    return json_error("Method Not Allowed", 405)


# ── потенциальные поставщики ────────────────────────────────────────────

@api_view(methods=("GET",), module="tender", level="read")
def prospect_list(request):
    return prospects.search(Ctx.from_request(request), (request.GET.get("q") or "").strip())


@api_view(methods=("POST",), module="tender", level="write", body=schemas.ProspectIn,
          status=201, idempotent=True)
def prospect_create(request, data):
    return prospects.out(prospects.create(Ctx.from_request(request), data.model_dump()))


def prospects_collection(request):
    if request.method == "GET":
        return prospect_list(request)
    if request.method == "POST":
        return prospect_create(request)
    return json_error("Method Not Allowed", 405)


@api_view(methods=("GET",), module="tender", level="read")
def prospect_get(request, prospect_id):
    return prospects.out(prospects.get(Ctx.from_request(request), prospect_id))


@api_view(methods=("PATCH",), module="tender", level="write", body=schemas.ProspectUpdate,
          idempotent=True)
def prospect_patch(request, prospect_id, data):
    sent = data.model_dump(exclude_unset=True)
    version = sent.pop("version", None)
    return prospects.out(prospects.update(Ctx.from_request(request), prospect_id,
                                          expected_version=version, data=sent))


def prospect_detail(request, prospect_id):
    if request.method == "GET":
        return prospect_get(request, prospect_id)
    if request.method == "PATCH":
        return prospect_patch(request, prospect_id)
    return json_error("Method Not Allowed", 405)


# ── контрагенты БЗО ─────────────────────────────────────────────────────

@api_view(methods=("GET",), module="tender", level="read")
def counterparty_search(request):
    """Только «Активен» — ``bpp.search_counterparties``; участником тендера
    другой и не станет (E-TND-02)."""
    Ctx.from_request(request).require("tender.tenders", "view", "Недостаточно прав на тендеры.")
    return bpp.search_counterparties((request.GET.get("q") or "").strip() or None,
                                     limit=SEARCH_LIMIT)
