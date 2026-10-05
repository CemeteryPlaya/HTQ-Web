"""Расчёты договора и счёта (этап 3, B3.1–B3.2): НДС, порог 1000 МРП,
сумма в KZT, остаток договора. Справочники — из сида ``refdata/0002``."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from apps.bpp.services import calc
from apps.refdata.models import Country, ExchangeRate, MrpValue
from htqweb.errors import DomainError

pytestmark = pytest.mark.django_db


# ── НДС ─────────────────────────────────────────────────────────────────

def test_vat_inside_the_amount_is_rounded_to_cents():
    # CALC-008: 1 160 000 × 16 / 116 = 160 000,00; 100 × 12 / 112 = 10,714… → 10,71
    assert calc.vat_amount(Decimal("1160000"), Decimal("16")) == Decimal("160000.00")
    assert calc.vat_amount(Decimal("100"), Decimal("12")) == Decimal("10.71")
    assert calc.without_vat(Decimal("100"), Decimal("12")) == Decimal("89.29")


def test_zero_or_missing_rate_means_no_vat():
    assert calc.vat_amount(Decimal("500"), Decimal("0")) == Decimal("0.00")
    assert calc.vat_amount(Decimal("500"), None) == Decimal("0.00")


def test_vat_rate_follows_the_document_date():
    # D-14: РК 12% до 01.01.2026, 16% с 01.01.2026
    before = calc.vat_for("KZ", date(2025, 12, 31))
    after = calc.vat_for("KZ", date(2026, 1, 1))
    assert (before.rate, before.source, before.warning) == (Decimal("12.00"), "refdata", None)
    assert (after.rate, after.source) == (Decimal("16.00"), "refdata")


def test_missing_rate_falls_back_to_sixteen_with_a_warning():
    Country.objects.get_or_create(code="CN", defaults={"name": "Китай"})
    pick = calc.vat_for("CN", date(2026, 9, 15))
    assert pick.rate == Decimal("16.00")
    assert pick.source == "default"
    assert pick.warning == ("Для страны Китай на 15.09.2026 не задана ставка НДС. "
                            "Подставлена 16% — проверьте ставку.")


# ── порог 1000 МРП ──────────────────────────────────────────────────────

def test_threshold_boundary_is_inclusive():
    # AC-005: МРП 2026 = 4 325 тг — 4 325 000,00 можно, 4 325 000,01 нельзя
    on = date(2026, 9, 12)
    calc.check_no_contract_threshold(Decimal("4325000.00"), on)
    with pytest.raises(DomainError) as exc:
        calc.check_no_contract_threshold(Decimal("4325000.01"), on)
    assert exc.value.code == "E-INV-01"
    assert exc.value.fields[0]["threshold"] == "4325000.00"


def test_threshold_message_is_the_tz_text():
    with pytest.raises(DomainError) as exc:
        calc.check_no_contract_threshold(Decimal("5100000"), date(2026, 9, 12))
    assert exc.value.message == ("Сумма счёта 5 100 000,00 тг превышает 1000 МРП "
                                 "(4 325 000,00 тг). Оплата без договора невозможна. "
                                 "Оформите договор.")


def test_threshold_uses_the_mrp_of_the_counterparty_invoice_date():
    # D-16, ТЗ §26.2: счёт контрагента прошлого года — прошлогодний МРП 3 932
    assert calc.threshold(date(2025, 12, 20)) == Decimal("3932000.00")
    calc.check_no_contract_threshold(Decimal("3932000.00"), date(2025, 12, 20))
    with pytest.raises(DomainError):
        calc.check_no_contract_threshold(Decimal("4000000.00"), date(2025, 12, 20))


def test_no_mrp_on_the_date_is_a_readable_error():
    MrpValue.objects.all().delete()
    with pytest.raises(DomainError) as exc:
        calc.threshold(date(2026, 9, 12))
    assert exc.value.code == "E-REF-04"
    assert "12.09.2026" in exc.value.message


# ── сумма в KZT ─────────────────────────────────────────────────────────

def test_kzt_is_taken_as_is():
    got = calc.to_kzt(Decimal("1000.005"), "KZT", date(2026, 9, 12))
    assert (got.amount_kzt, got.rate, got.source) == (Decimal("1000.01"), Decimal("1"), "kzt")


def test_foreign_currency_by_the_nbrk_rate_of_the_date():
    ExchangeRate.objects.create(currency_code="USD", on_date=date(2026, 9, 12),
                                rate=Decimal("512.345600"), source="nbrk")
    got = calc.to_kzt(Decimal("1000.00"), "USD", date(2026, 9, 12))
    assert got.amount_kzt == Decimal("512345.60")
    assert got.source == "nbrk"


def test_manual_rate_wins_over_the_nbrk_one():
    ExchangeRate.objects.create(currency_code="USD", on_date=date(2026, 9, 12),
                                rate=Decimal("512.00"), source="nbrk")
    got = calc.to_kzt(Decimal("10"), "USD", date(2026, 9, 12), manual_rate="515.50")
    assert (got.amount_kzt, got.source) == (Decimal("5155.00"), "manual")
    with pytest.raises(DomainError) as exc:
        calc.to_kzt(Decimal("10"), "USD", date(2026, 9, 12), manual_rate="0")
    assert exc.value.code == "E-VAL-01"


def test_missing_rate_refuses_instead_of_guessing():
    with pytest.raises(DomainError) as exc:
        calc.to_kzt(Decimal("10"), "EUR", date(2026, 9, 13))
    assert exc.value.code == "E-REF-05"
    assert "EUR" in exc.value.message and "13.09.2026" in exc.value.message


# ── остаток договора ────────────────────────────────────────────────────

def test_open_agreement_has_no_remaining():
    assert calc.agreement_remaining(None, Decimal("999")) is None
    calc.check_agreement_remaining(agreement_number="ДГ-2026-000001", agreement_amount=None,
                                   invoiced=Decimal("0"), invoice_amount=Decimal("10000000"))


def test_invoice_over_the_remaining_is_refused_with_the_excess():
    # AC-008: договор 10 000 000, счета 9 700 000, новый счёт 500 000 → превышение 200 000
    kwargs = dict(agreement_number="ДГ-2026-000012", agreement_amount=Decimal("10000000"),
                  invoiced=Decimal("9700000"))
    calc.check_agreement_remaining(invoice_amount=Decimal("300000"), **kwargs)
    with pytest.raises(DomainError) as exc:
        calc.check_agreement_remaining(invoice_amount=Decimal("500000"), **kwargs)
    assert exc.value.code == "E-INV-02"
    assert exc.value.message == ("Сумма счёта превышает остаток по договору ДГ-2026-000012 "
                                 "на 200 000,00 KZT. Уменьшите сумму или оформите "
                                 "дополнительное соглашение.")
    assert exc.value.fields[0]["remaining"] == "300000.00"
