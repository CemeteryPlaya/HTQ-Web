"""Ключи книги CashFlow при переносе (B6.2, D-B62-4): LARK договора и
отпечаток строки операции связываются с тем, чем документ стал, — новым
документом или сальдо статьи (закрытый)."""

from __future__ import annotations

import pytest

from apps.bpp.models import MigrationLink
from apps.bpp.services.migration import links
from apps.bpp.tests.test_files import memory_storage  # noqa: F401  (фикстура)
from apps.contracts.models import Agreement as OldAgreement
from apps.contracts.models import ContractPayment
from apps.contracts.models import Invoice as OldInvoice

from .common import migrate, write_maps
from .test_documents import _world

pytestmark = pytest.mark.django_db


def test_book_keys_point_at_the_new_document_or_the_saldo(company_context, tmp_path):
    slug = company_context["slug"]
    admin, steel, signed, running, framework = _world()
    OldAgreement.objects.filter(pk=signed.pk).update(external_id="L-SIGNED")
    OldAgreement.objects.filter(number="Д-3").update(external_id="L-EXECUTED")
    OldInvoice.objects.filter(status="approved").update(external_id="ops:open")
    OldInvoice.objects.filter(status="paid").update(external_id="ops:paid")
    ContractPayment.objects.filter(agreement=signed).update(external_id="ops:payment")

    migrate(slug, *write_maps(tmp_path, {admin.id: "ОБ-А"}, {steel.id: "T-METAL"}))

    def target(key_type, key):
        row = MigrationLink.objects.get(source_type=key_type, source_id=key)
        return row.target_type, row.target_id

    signed_new = links.target_of("contracts.agreement", signed.pk, "bpp.agreement")
    assert target("cashflow.agreement", "L-SIGNED") == ("bpp.agreement", signed_new)
    assert target("cashflow.agreement", "L-EXECUTED")[0] == "bpp.saldo"
    assert target("cashflow.operation", "ops:open")[0] == "bpp.invoice"
    assert target("cashflow.operation", "ops:paid")[0] == "bpp.saldo"
    assert target("cashflow.operation", "ops:payment")[0] == "bpp.invoice"
    # Сальдо у закрытых — одно на статью проекта.
    assert target("cashflow.agreement", "L-EXECUTED")[1] == \
        target("cashflow.operation", "ops:paid")[1]
