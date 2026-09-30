"""Помощники тестов альтернативных предложений (A5.1, план этапа 5 A).

Документы — фабриками B (``test_invoices.py``, ``test_agreements.py``): счёт
без договора «На рассмотрении ФД», договор «На согласовании». Пользователи
и роли — ``tests/stage2.py``: СН — ``bpp-sn``, ПМ — ``bpp-pm``.

Только для ORM-документов (гонки, ``transaction=True``, где посеянных ролей и
справочников уже нет) — ``orm_invoice_source``.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

from apps.bpp.models import (
    AgreementStatus,
    Counterparty,
    Invoice,
    InvoiceLine,
    InvoiceStatus,
    PurchaseRequest,
    PurchaseRequestItem,
)
from apps.bpp.services.agreements import agreements as agreement_service
from apps.bpp.services.alternatives import offers
from apps.bpp.services.core import files as core_files
from apps.bpp.tests import stage2 as s
from apps.bpp.tests import test_invoices as invoice_flow
from apps.bpp.tests.test_files import PDF

SN2, SN3, SN4 = s.SN2, 921, 922
INVOICE, AGREEMENT = offers.SOURCE_INVOICE, offers.SOURCE_AGREEMENT
JUSTIFICATION = "Ниже цена и короче срок поставки"


def sn(slug, user_id=s.SN):
    return s.actor(slug, user_id, "bpp-sn")


def pm(slug, user_id=s.PM):
    return s.actor(slug, user_id, "bpp-pm")


def cp(n: int) -> Counterparty:
    """Контрагент № ``n`` (n ≥ 2: № 1 — контрагент исходного документа тестов счёта)."""
    return invoice_flow._counterparty(f"10000000{n:04d}")


def invoice_on_review(slug, *amounts):
    """Счёт без договора «На рассмотрении ФД» от СН (``s.SN``) — ``(автор, проект, счёт)``."""
    return invoice_flow._submitted(slug, *amounts)


def agreement_on_review(slug, *amounts):
    """Договор «На согласовании» от СН (``s.SN``) — ``(автор, проект, договор)``."""
    proj = invoice_flow._setup(slug)
    author = s.actor(slug, s.SN, "bpp-sn")
    req = invoice_flow._approved_request(author, proj, *amounts)
    agr = agreement_service.create_from_plan(author, [str(i.id) for i in req.items.all()])
    agr, _ = agreement_service.update_draft(author, agr.id, expected_version=None, data={
        "counterparty_id": str(invoice_flow._counterparty("100000000009").pk),
        "ext_number": "Д-1", "ext_date": timezone.localdate()})
    agreement_service.submit(author, agr.id, expected_version=None)
    agr.refresh_from_db()
    assert agr.status == AgreementStatus.ON_REVIEW
    return author, proj, agr


def attach_kp(offer, actor) -> None:
    core_files.attach(offer, "alternative_offer", data=PDF, filename="кп.pdf",
                      mime="application/pdf", actor_id=actor.user_id)


def draft(actor, source, source_type=INVOICE):
    return offers.create(actor, source_type=source_type, source_id=source.pk)


def fill(actor, offer, counterparty, *, price=None, prices=None, kp=True, keep=None, **extra):
    """Заполнить черновик: контрагент, цены, срок, оплата, обоснование, КП.
    ``price`` — цена каждой позиции, ``prices`` — по позициям по порядку;
    ``keep`` — сколько первых позиций оставить в АП."""
    lines = list(offer.lines.order_by("created_at"))[:keep]
    values = prices or [price] * len(lines)
    data = {
        "counterparty_id": str(counterparty.pk),
        "lines": [{"source_line_id": str(line.source_line_id), "price": value}
                  for line, value in zip(lines, values, strict=True)],
        "delivery_date": timezone.localdate() + timedelta(days=10),
        "payment_terms": "postpay", "justification": JUSTIFICATION, **extra}
    offer = offers.update_draft(actor, offer.id, expected_version=None, data=data)
    if kp:
        attach_kp(offer, actor)
    return offer


def filed(actor, source, counterparty, *, price, source_type=INVOICE, **extra):
    """Создать, заполнить и подать АП с одной ценой на все позиции."""
    offer = fill(actor, draft(actor, source, source_type), counterparty, price=price, **extra)
    return offers.submit(actor, offer.id, expected_version=None)


def orm_invoice_source(amounts, *, author_id, alt_limit=3) -> Invoice:
    """Счёт без договора «На рассмотрении ФД» с позициями ``amounts`` прямо в
    базе — для транзакционных тестов (проекта, бюджета и маршрутов нет)."""
    project_id, today = uuid.uuid4(), timezone.localdate()
    request = PurchaseRequest.objects.create(
        number=f"ЗЗ-2026-{PurchaseRequest.objects.count() + 1:06d}", author_id=author_id,
        initiator_role="sn", project_id=project_id, article_id=uuid.uuid4(),
        purchase_type="goods", need_date=today, status="approved")
    inv = Invoice.objects.create(
        number=f"СЧ-2026-{Invoice.objects.count() + 1:06d}", project_id=project_id,
        article_id=request.article_id, ext_number="1", ext_date=today,
        amount=sum(Decimal(str(a)) for a in amounts), status=InvoiceStatus.UNDER_REVIEW,
        author_id=author_id, alt_limit=alt_limit)
    for n, amount in enumerate(amounts, start=1):
        item = PurchaseRequestItem.objects.create(
            request=request, line_no=n, sys_number=f"{request.number}-{n}", name=f"Позиция {n}",
            uom_id=uuid.uuid4(), qty=1, price=amount, amount=amount, need_date=today,
            executor_id=author_id)
        InvoiceLine.objects.create(invoice=inv, request_item=item, qty=1, amount=amount)
    return inv


__all__ = ["AGREEMENT", "INVOICE", "SN2", "SN3", "SN4", "agreement_on_review",
           "attach_kp", "cp", "draft", "fill", "filed", "invoice_on_review",
           "orm_invoice_source", "pm", "sn"]
