"""Номер счёта в назначении платежа и распределение суммы (A4.2, часть 1)."""

from __future__ import annotations

from decimal import Decimal

from apps.bpp.services.bank import recon

D = Decimal


def test_find_numbers_normalizes_latin_case_spaces_and_dashes():
    want = ["СЧ-2026-000123"]
    assert recon.find_numbers("оплата по счёту cч - 2026 - 000123") == want
    assert recon.find_numbers("СЧ2026000123") == want
    assert recon.find_numbers("сч—2026—000123") == want
    assert recon.find_numbers("CЧ-2026-000123") == want


def test_find_numbers_several_in_order_without_duplicates():
    text = "СЧ-2026-000002, сч-2026-000001, СЧ-2026-000002"
    assert recon.find_numbers(text) == ["СЧ-2026-000002", "СЧ-2026-000001"]


def test_find_numbers_rejects_wrong_lengths():
    assert recon.find_numbers("СЧ-2026-0001234") == []
    assert recon.find_numbers("СЧ-20260-000123") == []
    assert recon.find_numbers("") == []
    assert recon.find_numbers("на сумму 2026000123") == []


def test_find_numbers_word_boundary_nbsp_and_minus():
    assert recon.find_numbers("РАСЧ 2026 000123") == []
    assert recon.find_numbers("СЧ 2026 000123") == ["СЧ-2026-000123"]
    assert recon.find_numbers("СЧ−2026−000123") == ["СЧ-2026-000123"]


def test_distribute_exact_and_ambiguous():
    rem = [("A", D("400")), ("B", D("600"))]
    assert recon.distribute(D("1000"), rem) == ([("A", D("400")), ("B", D("600"))], True)
    assert recon.distribute(D("900"), rem) == ([("A", D("400")), ("B", D("500"))], False)
    assert recon.distribute(D("1200"), rem) == ([("A", D("400")), ("B", D("600"))], False)


def test_distribute_non_positive_amount():
    rem = [("A", D("400"))]
    assert recon.distribute(D("0"), rem) == ([], False)
    assert recon.distribute(D("-5"), rem) == ([], False)
