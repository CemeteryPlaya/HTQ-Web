"""Перенесённое в реестрах (B6.1, задача 7, D-B61-8): договоры, счета и
подотчёт видны как обычные, с признаком ``is_migrated``; технические заявки
переноса скрыты из реестра заявок и Плана закупок."""

from __future__ import annotations

import pytest

from apps.bpp.models import PurchaseRequest
from apps.bpp.services.accountable import read as accountable_read
from apps.bpp.services.agreements import read as agreements_read
from apps.bpp.services.invoices import read as invoices_read
from apps.bpp.services.plan import service as plan
from apps.bpp.services.requests import read as requests_read
from apps.bpp.tests import stage2 as s
from apps.bpp.tests.test_files import memory_storage  # noqa: F401  (фикстура)

from .common import migrate, write_maps
from .test_documents import _world

pytestmark = pytest.mark.django_db


def test_migrated_documents_are_listed_and_technical_requests_are_not(company_context,
                                                                      tmp_path):
    slug = company_context["slug"]
    admin, steel, *_ = _world()
    migrate(slug, *write_maps(tmp_path, {admin.id: "ОБ-А"}, {steel.id: "T-METAL"}))
    root = s.actor(slug, 999, superuser=True)

    agreements = agreements_read.registry(root)["items"]
    assert len(agreements) == 3 and all(row["is_migrated"] for row in agreements)
    invoices = invoices_read.registry(root)["items"]
    assert invoices and all(row["is_migrated"] for row in invoices)
    accountable = accountable_read.registry(root)["items"]
    assert [row["is_migrated"] for row in accountable] == [True]

    assert PurchaseRequest.objects.filter(is_migrated=True).exists()
    assert requests_read.registry(root)["total"] == 0
    assert not plan._base().exists()
