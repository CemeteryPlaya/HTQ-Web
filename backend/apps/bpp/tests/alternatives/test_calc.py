"""CALC-013 и суммы альтернативного предложения — чистые функции (план
этапа 5 A, задача 1). БД не нужна."""

from __future__ import annotations

from decimal import Decimal

from apps.bpp.services.alternatives import calc


def test_saving_positive_and_negative():
    # AC-014: исходный счёт 2 800 000, альтернатива 2 450 000.
    assert calc.saving(Decimal("2800000"), Decimal("2450000")) == (
        Decimal("350000.00"), Decimal("12.50"))
    # Удорожание — отрицательная экономия.
    assert calc.saving(Decimal("3900000"), Decimal("4500000")) == (
        Decimal("-600000.00"), Decimal("-15.38"))


def test_saving_values_are_quantized_to_cents():
    amount, pct = calc.saving(Decimal("2800000"), Decimal("2450000"))
    assert amount.as_tuple().exponent == -2
    assert pct.as_tuple().exponent == -2


def test_saving_pct_rounds_half_up():
    # 1 / 20000 = 0,005 % — ровно половина: ROUND_HALF_UP даёт 0,01, а
    # банковское округление контекста Decimal дало бы 0,00.
    assert calc.saving(Decimal("20000"), Decimal("19999"))[1] == Decimal("0.01")
    assert calc.saving(Decimal("20000"), Decimal("20001"))[1] == Decimal("-0.01")


def test_offer_amount_rounds_per_line():
    # 3 × 33,335 = 100,005 → 100,01 (ROUND_HALF_UP по строке, CALC-004).
    assert calc.offer_amount([(Decimal("3"), Decimal("33.335"))]) == Decimal("100.01")


def test_offer_amount_sums_rounded_lines():
    lines = [(Decimal("3"), Decimal("33.335")), (Decimal("1.5"), Decimal("10.01"))]
    # 100,01 + (15,015 → 15,02) = 115,03
    assert calc.offer_amount(lines) == Decimal("115.03")
    assert calc.offer_amount([]) == Decimal("0.00")


def test_source_part_sums_chosen_lines():
    lines = [(Decimal("2"), Decimal("1000.00")), (Decimal("5"), Decimal("250.50"))]
    assert calc.source_part(lines) == Decimal("1250.50")
    assert calc.source_part([]) == Decimal("0.00")


def test_source_price_divides_amount_by_qty():
    assert calc.source_price(Decimal("100.00"), Decimal("3")) == Decimal("33.33")


def test_saving_on_zero_source_is_zero_pct():
    assert calc.saving(Decimal("0"), Decimal("1500")) == (Decimal("-1500.00"), Decimal("0.00"))
    assert calc.saving(Decimal("0.00"), Decimal("0")) == (Decimal("0.00"), Decimal("0.00"))


def test_partial_offer_in_other_currency_saving_from_source_part():
    """Review Focus 3: счёт в USD (курс 500) на A, B, C; АП в KZT на A и B.
    Исходная часть — (A + B) по курсу счёта, процент — от неё, C не входит."""
    rate = Decimal("500")
    source_lines = {"A": (Decimal("2"), Decimal("1000.00")),
                    "B": (Decimal("1"), Decimal("600.00")),
                    "C": (Decimal("4"), Decimal("9999.00"))}
    part_kzt = calc.source_part([source_lines["A"], source_lines["B"]]) * rate
    offer_kzt = calc.offer_amount([(Decimal("2"), Decimal("200000")),
                                   (Decimal("1"), Decimal("300000"))])
    assert part_kzt == Decimal("800000.00")
    assert offer_kzt == Decimal("700000.00")
    assert calc.saving(part_kzt, offer_kzt) == (Decimal("100000.00"), Decimal("12.50"))
