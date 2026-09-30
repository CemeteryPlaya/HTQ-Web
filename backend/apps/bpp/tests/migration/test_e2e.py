"""Сквозная проверка B6.1: «Договоры» → перенос → работа с перенесённым как
с обычными документами модуля, остатки при этом не плывут."""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from apps.bpp.models import AccountableFundsRequest, Agreement, Invoice
from apps.bpp.services.accountable import accountable as accountable_service
from apps.bpp.services.budget import committed
from apps.bpp.services.invoices import invoices as invoice_service
from apps.bpp.services.invoices import payments
from apps.bpp.tests import stage2 as s
from apps.bpp.tests.test_files import PDF, memory_storage  # noqa: F401  (фикстура)

from .common import migrate, write_maps
from .test_documents import _world

pytestmark = pytest.mark.django_db
BUH = 907


def test_work_continues_on_migrated_documents(company_context, tmp_path):
    slug = company_context["slug"]
    admin, steel, *_ = _world()
    migrate(slug, *write_maps(tmp_path, {admin.id: "ОБ-А"}, {steel.id: "T-METAL"}))
    agreement = Agreement.objects.get(ext_number="Д-1")
    before = committed.committed_by_article(agreement.project_id)[str(agreement.article_id)]

    # БУХ отмечает оплату перенесённого счёта «К оплате».
    to_pay = Invoice.objects.get(basis="no_contract", status="to_pay")
    s.user(BUH)
    paid = payments.mark_paid(s.actor(slug, BUH, "bpp-buh"), to_pay.id,
                              pay_date=timezone.localdate(), amount=to_pay.amount,
                              pp_number="5001")
    assert paid.status == "paid"

    # Автор оформляет новый счёт по перенесённому действующему договору:
    # позиции договора — позиции его технической заявки, остаток учтён.
    author = s.actor(slug, 7, "bpp-sn")
    fresh = invoice_service.create_from_agreement(author, agreement.id)
    assert fresh.agreement_id == agreement.pk and fresh.lines.count() == 2
    assert not fresh.is_migrated

    # Подотчётное лицо добавляет авансовый отчёт к перенесённой заявке.
    request = AccountableFundsRequest.objects.get()
    report = accountable_service.add_report(
        author, request.id, expense_name="Перчатки", amount=Decimal("2000.00"),
        upload=SimpleUploadedFile("chek.pdf", PDF, content_type="application/pdf"))
    assert report.request_id == request.pk

    # Черновик счёта и отчёт резерв статьи не меняют.
    assert committed.committed_by_article(agreement.project_id)[str(agreement.article_id)] \
        == before
