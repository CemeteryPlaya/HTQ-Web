"""Связи переноса из ``contracts`` (B6.1, D-B61-9): на них держится
повторный прогон без дублей и подпись «перенесён в …» в замороженном
разделе (A6.2)."""

from __future__ import annotations

import pytest

from apps.bpp import interface
from apps.bpp.models import MigrationLink
from apps.bpp.services.migration import links
from apps.bpp.tests import stage2 as s

pytestmark = pytest.mark.django_db


def test_link_is_idempotent_and_refuses_a_second_target(company_context):
    links.link("contracts.agreement", 7, "bpp.agreement", "a-1")
    links.link("contracts.agreement", 7, "bpp.agreement", "a-1")      # повтор — то же
    assert MigrationLink.objects.count() == 1
    assert links.target_of("contracts.agreement", 7, "bpp.agreement") == "a-1"
    with pytest.raises(links.LinkConflict):
        links.link("contracts.agreement", 7, "bpp.agreement", "a-2")


def test_one_source_may_give_targets_of_different_types(company_context):
    links.link("contracts.agreement", 7, "bpp.agreement", "a-1")
    links.link("contracts.agreement", 7, "bpp.purchase_request", "r-1")
    assert links.target_of("contracts.agreement", 7, "bpp.purchase_request") == "r-1"
    assert links.target_of("contracts.agreement", 8, "bpp.agreement") is None


def test_migrated_targets_carry_the_document_number(company_context):
    """Заморозка ``contracts`` спрашивает через интерфейс и получает номер
    документа модуля; неперенесённые записи в ответ не попадают."""
    slug = company_context["slug"]
    budget = s.approved_budget(slug, s.project(), {s.metal(): 1000})
    links.link("contracts.budget", 3, "bpp.budget", budget.pk)

    answer = interface.migrated_targets("contracts.budget", [3, 4])
    assert answer == {"3": [{"target_type": "bpp.budget", "target_id": str(budget.pk),
                             "number": budget.number}]}
