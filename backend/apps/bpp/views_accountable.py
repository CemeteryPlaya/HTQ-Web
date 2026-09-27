"""Ручки подотчётных средств — подмодуль ``bpp_accountable`` (задача B4.1).

Каждая — под гейтом модуля ``bpp`` с явным уровнем; узлы
``bpp.accountable`` / ``bpp.accountable.payment`` и принадлежность проверяет
сервис. Согласование заявки и отчётов — ручки ``signoff``.
"""

from __future__ import annotations

from htqweb.errors import DomainError
from htqweb.http import api_view, json_error

from .schemas import accountable as schemas
from .services.accountable import accountable as service
from .services.actor import Actor


def _card(request, req) -> dict:
    actor = Actor(request)
    return service.card(actor, service.get_visible(actor, req.pk))


@api_view(methods=("GET",), module="bpp", level="read")
def accountable_list(request):
    return service.registry(Actor(request), status=request.GET.get("status") or None)


@api_view(methods=("POST",), module="bpp", level="write", body=schemas.AccountableCreate,
          status=201, idempotent=True)
def accountable_create(request, data):
    return _card(request, service.create(Actor(request), **data.model_dump()))


def accountable_collection(request):
    if request.method == "GET":
        return accountable_list(request)
    if request.method == "POST":
        return accountable_create(request)
    return json_error("Method Not Allowed", 405)


@api_view(methods=("GET",), module="bpp", level="read")
def accountable_get(request, request_id):
    actor = Actor(request)
    return service.card(actor, service.get_visible(actor, request_id))


@api_view(methods=("PATCH",), module="bpp", level="write", body=schemas.AccountableUpdate,
          idempotent=True)
def accountable_patch(request, request_id, data):
    actor = Actor(request)
    service.get_visible(actor, request_id)
    sent = data.model_dump(exclude_unset=True)
    return _card(request, service.update_draft(actor, request_id,
                                               expected_version=sent.pop("version", None),
                                               data=sent))


@api_view(methods=("DELETE",), module="bpp", level="write", idempotent=True)
def accountable_delete(request, request_id):
    actor = Actor(request)
    service.get_visible(actor, request_id)
    version = request.GET.get("version")
    service.delete_draft(actor, request_id,
                         expected_version=int(version) if version and version.isdigit() else None)
    return {"deleted": True}


def accountable_detail(request, request_id):
    if request.method == "GET":
        return accountable_get(request, request_id)
    if request.method == "PATCH":
        return accountable_patch(request, request_id)
    if request.method == "DELETE":
        return accountable_delete(request, request_id)
    return json_error("Method Not Allowed", 405)


@api_view(methods=("POST",), module="bpp", level="write", body=schemas.VersionOnly,
          idempotent=True)
def accountable_submit(request, request_id, data):
    actor = Actor(request)
    service.get_visible(actor, request_id)
    return _card(request, service.submit(actor, request_id, expected_version=data.version))


@api_view(methods=("POST",), module="bpp", level="write", body=schemas.VersionOnly,
          idempotent=True)
def accountable_mark_paid(request, request_id, data):
    actor = Actor(request)
    service.get_visible(actor, request_id)
    return _card(request, service.mark_paid(actor, request_id, expected_version=data.version))


@api_view(methods=("POST",), module="bpp", level="write", status=201, idempotent=True)
def accountable_add_report(request, request_id):
    """Авансовый отчёт: multipart — ``expense_name``, ``amount``, ``file``."""
    actor = Actor(request)
    service.get_visible(actor, request_id)
    try:
        amount = request.POST.get("amount") or "0"
        report = service.add_report(actor, request_id,
                                    expense_name=request.POST.get("expense_name", ""),
                                    amount=amount, upload=request.FILES.get("file"))
    except ArithmeticError as exc:
        raise DomainError("E-VAL-01", "Сумма указана неверно.",
                          fields=[{"field": "amount", "message": "Число"}]) from exc
    return service.serialize_report(report)


@api_view(methods=("POST",), module="bpp", level="write", idempotent=True)
def report_submit(request, report_id):
    actor = Actor(request)
    service.get_visible_report(actor, report_id)
    return service.serialize_report(service.submit_report(actor, report_id))


@api_view(methods=("GET",), module="bpp", level="read")
def report_file_link(request, report_id):
    return service.report_file_link(Actor(request), report_id)
