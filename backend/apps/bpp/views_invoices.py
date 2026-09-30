"""Ручки счёта на оплату — подмодуль ``bpp_invoices`` (ТЗ §10, §23; B3.2).

Каждая — под гейтом модуля ``bpp`` с явным уровнем; права тоньше уровня
(узлы ``bpp.invoices``, ``.decision``, ``.payment``, ``.closing_docs``),
авторство и видимость проверяют сервисы. Записывающие ручки идемпотентны
(``Idempotency-Key``, AC-013).
"""

from __future__ import annotations

from datetime import date

from django.utils import timezone

from htqweb.errors import DomainError
from htqweb.http import api_view, json_error

from .models import ReconStatus
from .schemas import invoices as schemas
from .services import calc
from .services.actor import Actor
from .services.core import export
from .services.invoices import decisions, payments, read
from .services.invoices import invoices as service
from .services.params import int_param


def _card(request, inv, *, vat_warning: str | None = None) -> dict:
    return read.card(Actor(request), inv, vat_warning=vat_warning)


def _list_param(request, name: str) -> list[str]:
    return [value for value in request.GET.getlist(name) if value]


def _date_param(request, name: str) -> str | None:
    """ГГГГ-ММ-ДД или пусто; строкой — фильтры уходят и в фоновую выгрузку
    (JSON задачи)."""
    raw = request.GET.get(name) or None
    if raw is None:
        return None
    try:
        return date.fromisoformat(raw).isoformat()
    except ValueError:
        raise DomainError("E-VAL-01", "Дата — в формате ГГГГ-ММ-ДД.",
                          fields=[{"field": name, "message": "Дата ГГГГ-ММ-ДД"}]) from None


def _recon_statuses(request) -> list[str]:
    """Повторяемый ``recon_status``; неизвестное значение — 422, а не тихо
    пустой реестр (опечатка в ссылке дашборда видна сразу)."""
    values = _list_param(request, "recon_status")
    unknown = [value for value in values if value not in ReconStatus.values]
    if unknown:
        raise DomainError("E-VAL-01", f"Неизвестный статус сверки: {', '.join(unknown)}.",
                          fields=[{"field": "recon_status",
                                   "message": "Допустимо: " + ", ".join(ReconStatus.values)}])
    return values


EXPORT_COLUMNS = (
    export.Column("number", "Номер"),
    export.Column("status", "Статус"),
    export.Column("ext_number", "Номер счёта контрагента"),
    export.Column("ext_date", "Дата счёта", kind="date"),
    export.Column("counterparty_name", "Контрагент"),
    export.Column("counterparty_reg_number", "БИН/ИИН"),
    export.Column("basis", "Основание"),
    export.Column("agreement_number", "Договор"),
    export.Column("project_code", "Проект"),
    export.Column("article_name", "Статья бюджета"),
    export.Column("amount", "Сумма", kind="money"),
    export.Column("currency_code", "Валюта"),
    export.Column("amount_kzt", "Сумма в KZT", kind="money"),
    export.Column("due_date", "Срок оплаты", kind="date"),
    export.Column("planned_pay_date", "Плановая дата оплаты", kind="date"),
    export.Column("paid_bank_amount", "Оплачено по банку", kind="money"),
    export.Column("author_name", "Автор"),
)

QUEUE_COLUMNS = (
    export.Column("number", "Номер счёта"),
    export.Column("counterparty", "Контрагент"),
    export.Column("reg_number", "БИН/ИИН"),
    export.Column("iban", "IBAN"),
    export.Column("amount", "Сумма к оплате", kind="money"),
    export.Column("currency_code", "Валюта"),
    export.Column("planned_pay_date", "Плановая дата оплаты", kind="date"),
    export.Column("purpose", "Назначение платежа"),
)


@api_view(methods=("GET",), module="bpp", level="read")
def invoice_list(request):
    params = request.GET
    filters = {
        "tab": params.get("tab") or None,
        "statuses": _list_param(request, "status"),
        "project_ids": _list_param(request, "project_id"),
        "article_ids": _list_param(request, "article_id"),
        "counterparty_id": params.get("counterparty_id") or None,
        "basis": params.get("basis") or None,
        "agreement_id": params.get("agreement_id") or None,
        "date_from": params.get("date_from") or None,
        "date_to": params.get("date_to") or None,
        "search": params.get("search") or None,
        # Для ссылок дашборда D-01 (D-S4-8, задача A4.3).
        "author_id": int_param(params, "author_id"),
        "recon_statuses": _recon_statuses(request),
        "bank_date_from": _date_param(request, "bank_date_from"),
        "bank_date_to": _date_param(request, "bank_date_to"),
        "bank_wait_days": int_param(params, "bank_wait_days", minimum=0),
    }
    actor = Actor(request)
    if params.get("format") == "xlsx":
        kwargs = {**actor.export_identity(), "filters": filters}
        return export.respond(
            request, name="Счета на оплату", columns=EXPORT_COLUMNS,
            rows=read.export_rows(**kwargs), count=read.export_count(**kwargs),
            rebuild=(read.EXPORT_REBUILD_PATH, kwargs))
    return read.registry(actor, filters=filters,
                         page=int_param(params, "page", 1, minimum=1),
                         page_size=int_param(params, "page_size", 50))


@api_view(methods=("POST",), module="bpp", level="write", body=schemas.InvoiceCreate,
          status=201, idempotent=True)
def invoice_create(request, data):
    actor = Actor(request)
    if data.agreement_id:
        inv = service.create_from_agreement(actor, str(data.agreement_id),
                                            item_ids=[str(i) for i in data.item_ids] or None)
    else:
        if not data.item_ids:
            raise DomainError("E-VAL-01", "Отметьте позиции плана или выберите договор.",
                              fields=[{"field": "item_ids", "message": "Нет позиций"}])
        inv = service.create_from_plan(actor, [str(i) for i in data.item_ids], role=data.role)
    return _card(request, inv)


def invoices_collection(request):
    if request.method == "GET":
        return invoice_list(request)
    if request.method == "POST":
        return invoice_create(request)
    return json_error("Method Not Allowed", 405)


@api_view(methods=("GET",), module="bpp", level="read")
def invoice_get(request, invoice_id):
    actor = Actor(request)
    return read.card(actor, service.get_visible(actor, invoice_id))


@api_view(methods=("PATCH",), module="bpp", level="write", body=schemas.InvoiceUpdate,
          idempotent=True)
def invoice_patch(request, invoice_id, data):
    actor = Actor(request)
    service.get_visible(actor, invoice_id)
    sent = data.model_dump(exclude_unset=True)
    version = sent.pop("version", None)
    if sent.get("counterparty_id") is not None:
        sent["counterparty_id"] = str(sent["counterparty_id"])
    inv, warning = service.update_draft(actor, invoice_id, expected_version=version, data=sent)
    return _card(request, inv, vat_warning=warning)


@api_view(methods=("DELETE",), module="bpp", level="write", idempotent=True)
def invoice_delete(request, invoice_id):
    actor = Actor(request)
    service.get_visible(actor, invoice_id)
    version = request.GET.get("version")
    service.delete_draft(actor, invoice_id, expected_version=int(version) if version else None)
    return {"deleted": True}


def invoice_detail(request, invoice_id):
    if request.method == "GET":
        return invoice_get(request, invoice_id)
    if request.method == "PATCH":
        return invoice_patch(request, invoice_id)
    if request.method == "DELETE":
        return invoice_delete(request, invoice_id)
    return json_error("Method Not Allowed", 405)


@api_view(methods=("POST",), module="bpp", level="write", body=schemas.InvoiceSubmit,
          idempotent=True)
def invoice_submit(request, invoice_id, data):
    actor = Actor(request)
    service.get_visible(actor, invoice_id)
    return _card(request, service.submit(actor, invoice_id, expected_version=data.version,
                                         counterparty_confirmed=data.counterparty_confirmed))


@api_view(methods=("POST",), module="bpp", level="write", body=schemas.WithComment,
          idempotent=True)
def invoice_cancel(request, invoice_id, data):
    actor = Actor(request)
    service.get_visible(actor, invoice_id)
    return _card(request, service.cancel(actor, invoice_id, expected_version=data.version,
                                         comment=data.comment))


@api_view(methods=("POST",), module="bpp", level="write", body=schemas.Decision,
          idempotent=True)
def invoice_decision(request, invoice_id, data):
    actor = Actor(request)
    service.get_visible(actor, invoice_id)
    return _card(request, decisions.decide(actor, invoice_id, decision=data.decision,
                                           planned_pay_date=data.planned_pay_date,
                                           comment=data.comment))


@api_view(methods=("POST",), module="bpp", level="write", body=schemas.BatchDecision,
          idempotent=True)
def invoice_batch_decision(request, data):
    return decisions.decide_batch(Actor(request), [str(i) for i in data.invoice_ids],
                                  decision=data.decision, comment=data.comment,
                                  planned_pay_date=data.planned_pay_date)


@api_view(methods=("POST",), module="bpp", level="write", body=schemas.Payment,
          status=201, idempotent=True)
def invoice_payment(request, invoice_id, data):
    actor = Actor(request)
    service.get_visible(actor, invoice_id)
    return _card(request, payments.mark_paid(actor, invoice_id, pay_date=data.pay_date,
                                             amount=data.amount, pp_number=data.pp_number,
                                             rate=data.rate))


@api_view(methods=("POST",), module="bpp", level="write", body=schemas.WithComment,
          idempotent=True)
def invoice_payment_cancel(request, invoice_id, mark_id, data):
    actor = Actor(request)
    service.get_visible(actor, invoice_id)
    return _card(request, payments.unmark(actor, invoice_id, mark_id, comment=data.comment))


@api_view(methods=("POST",), module="bpp", level="write", body=schemas.DocsRequest,
          idempotent=True)
def invoice_request_docs(request, invoice_id, data):
    actor = Actor(request)
    service.get_visible(actor, invoice_id)
    docs = {"avr": data.avr, "waybill": data.waybill, "vat_invoice": data.vat_invoice}
    return _card(request, payments.request_docs(actor, invoice_id, docs=docs,
                                                comment=data.comment))


@api_view(methods=("POST",), module="bpp", level="write", idempotent=True)
def invoice_submit_docs(request, invoice_id):
    actor = Actor(request)
    service.get_visible(actor, invoice_id)
    return _card(request, payments.submit_docs(actor, invoice_id))


@api_view(methods=("POST",), module="bpp", level="write", idempotent=True)
def invoice_accept_docs(request, invoice_id):
    actor = Actor(request)
    service.get_visible(actor, invoice_id)
    return _card(request, payments.accept_docs(actor, invoice_id))


@api_view(methods=("POST",), module="bpp", level="write", body=schemas.WithComment,
          idempotent=True)
def invoice_return_docs(request, invoice_id, data):
    actor = Actor(request)
    service.get_visible(actor, invoice_id)
    return _card(request, payments.return_docs(actor, invoice_id, comment=data.comment))


@api_view(methods=("GET",), module="bpp", level="read")
def invoice_threshold(request):
    """GetMrpThreshold (ТЗ §23): порог 1000 МРП на дату счёта для формы."""
    raw = request.GET.get("date")
    try:
        on_date = date.fromisoformat(raw) if raw else timezone.localdate()
    except ValueError as exc:
        raise DomainError("E-VAL-01", "Дата — в формате ГГГГ-ММ-ДД.") from exc
    return {"date": on_date, "threshold": calc.threshold(on_date)}


@api_view(methods=("GET",), module="bpp", level="read")
def invoice_export_queue(request):
    """«Экспорт очереди к оплате» (ТЗ §10.5) — БУХ."""
    actor = Actor(request)
    if not actor.can("bpp.invoices.payment", "edit"):
        raise DomainError("E-ACC-01", "Очередь к оплате выгружает бухгалтер. Если это ошибка, "
                                      "обратитесь к администратору.", status=403)
    kwargs = actor.export_identity()
    return export.respond(
        request, name="Очередь к оплате", columns=QUEUE_COLUMNS,
        rows=read.queue_rows(**kwargs), count=read.queue_count(**kwargs),
        rebuild=(read.QUEUE_REBUILD_PATH, kwargs))
