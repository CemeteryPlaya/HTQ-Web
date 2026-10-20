"""Контрагент из потенциального поставщика тендера (T5.4, зона A).

Передача выбора в БЗО (этап 5 тендера) превращает потенциального поставщика —
реквизиты, которые он ввёл в портале, — в карточку контрагента. Совпадение
страна + рег. номер — привязка к существующей карточке, а не дубль; без метки
«Проверенный» (D-20)."""

from __future__ import annotations

import pytest

from apps.bpp import interface
from apps.bpp.management.commands.seed_bpp_demo import bin_with_checksum
from apps.bpp.models import Counterparty
from apps.bpp.tests import stage2 as s
from htqweb.errors import DomainError

pytestmark = pytest.mark.django_db

BIN = bin_with_checksum("99034000001")


def _prospect(**over) -> interface.ProspectIn:
    data = {"name": "ТОО «Демо Снаб»", "country_code": "KZ", "reg_number": BIN,
            "is_vat_payer": False, "contact_name": "Сейткали А.", "phone": "+77010000001",
            "email": "offers@demo-snab.kz", "tender_number": "ТН-2026-000002"}
    return interface.ProspectIn(**{**data, **over})


def _buyer(slug: str) -> interface.TenderActor:
    s.user(s.SN)
    s.grant(slug, s.SN, "bpp-sn")
    return interface.TenderActor(user_id=s.SN)


def test_new_prospect_becomes_active_counterparty(company_context):
    actor = _buyer(company_context["slug"])
    ref = interface.create_counterparty_from_prospect(_prospect(), actor=actor)
    assert (ref.created, ref.status) == (True, "active")
    cp = Counterparty.objects.get(pk=ref.id)
    assert (cp.name, cp.country_code, cp.reg_number, cp.kind) == (
        "ТОО «Демо Снаб»", "KZ", BIN, "legal")
    assert cp.verified_override is None and cp.email == "offers@demo-snab.kz"


def test_existing_reg_number_is_linked_not_duplicated(company_context):
    actor = _buyer(company_context["slug"])
    first = interface.create_counterparty_from_prospect(_prospect(), actor=actor)
    again = interface.create_counterparty_from_prospect(
        _prospect(name="ТОО «Демо Снаб» (другое написание)"), actor=actor)
    assert (again.id, again.created) == (first.id, False)
    assert Counterparty.objects.filter(reg_number=BIN).count() == 1


def test_blocked_counterparty_is_refused(company_context):
    actor = _buyer(company_context["slug"])
    ref = interface.create_counterparty_from_prospect(_prospect(), actor=actor)
    Counterparty.objects.filter(pk=ref.id).update(status="blocked")
    with pytest.raises(DomainError) as exc:
        interface.create_counterparty_from_prospect(_prospect(), actor=actor)
    assert exc.value.code == "E-TND-14" and "заблокирован" in exc.value.message.lower()


def test_empty_reg_number_is_refused(company_context):
    actor = _buyer(company_context["slug"])
    with pytest.raises(DomainError) as exc:
        interface.create_counterparty_from_prospect(_prospect(reg_number=" "), actor=actor)
    assert exc.value.code == "E-TND-14"
    assert exc.value.fields[0]["field"] == "reg_number"
    assert not Counterparty.objects.exists()


def test_actor_without_create_right_is_403(company_context):
    s.user(s.SN)                               # без роли bpp-sn — права create нет
    with pytest.raises(DomainError) as exc:
        interface.create_counterparty_from_prospect(
            _prospect(), actor=interface.TenderActor(user_id=s.SN))
    assert exc.value.status == 403
    assert not Counterparty.objects.exists()
