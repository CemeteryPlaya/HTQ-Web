"""Расчёты договора и счёта — чистые функции этапа 3 (B3.1–B3.3), без моделей.

Написаны до моделей договора и счёта (те ссылаются на контрагента, A2.3),
чтобы этап 3 собирался на готовых и проверенных формулах:

- НДС внутри суммы — CALC-008, ставка страны на дату с запасной 16% (D-14);
- порог 1000 МРП для счёта без договора — BR-040, CALC-011 (D-16: сумма в
  KZT с НДС, МРП на дату счёта контрагента);
- сумма в KZT по курсу НБРК на дату или по фактическому курсу — CALC-012 (D-15);
- остаток закрытого договора — CALC-009, проверка BR-041.

Тексты ошибок — дословно ТЗ §26.1 с подстановкой.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from apps.refdata import interface as refdata
from htqweb.errors import DomainError

from .money import fmt, money

ZERO = Decimal("0.00")
#: Ставка, если в справочнике «страна × дата» её нет (D-14): документ не
#: блокируется, ставка подставляется и подсвечивается ФД.
DEFAULT_VAT_RATE = Decimal("16.00")
KZT = "KZT"


# ── НДС (CALC-008, D-14) ────────────────────────────────────────────────

def vat_amount(amount, rate) -> Decimal:
    """Сумма НДС внутри суммы: ``ROUND(сумма × ставка / (100 + ставка), 2)``."""
    if not rate:
        return ZERO
    rate = Decimal(rate)
    return money(Decimal(amount) * rate / (Decimal("100") + rate))


def without_vat(amount, rate) -> Decimal:
    return money(amount) - vat_amount(amount, rate)


@dataclass(frozen=True)
class VatPick:
    rate: Decimal
    source: str          # "refdata" — из справочника; "default" — запасная 16%
    warning: str | None  # текст для ФД, если ставка подставлена


def vat_for(country_code: str, on_date: date) -> VatPick:
    """Ставка НДС страны контрагента на дату документа (ТЗ §9.2)."""
    rate = refdata.vat_rate(country_code, on_date)
    if rate is not None:
        return VatPick(rate=rate, source="refdata", warning=None)
    country = refdata.country_brief([country_code]).get(country_code, {}).get("name",
                                                                              country_code)
    return VatPick(
        rate=DEFAULT_VAT_RATE, source="default",
        warning=(f"Для страны {country} на {on_date:%d.%m.%Y} не задана ставка НДС. "
                 f"Подставлена {DEFAULT_VAT_RATE:.0f}% — проверьте ставку."))


# ── порог 1000 МРП (BR-040, CALC-011, D-16) ─────────────────────────────

def threshold(on_date: date) -> Decimal:
    """1000 × МРП на дату счёта контрагента: черновик прошлого года — по
    прошлогоднему МРП (ТЗ §26.2)."""
    try:
        return refdata.contract_threshold(on_date)
    except refdata.RefdataMissing as exc:
        raise DomainError(
            "E-REF-04", f"В справочнике нет МРП на {on_date:%d.%m.%Y}. Обратитесь к "
                        f"администратору справочников.",
            fields=[{"field": "ext_date", "message": "Нет МРП на дату"}]) from exc


def check_no_contract_threshold(amount_kzt, on_date: date) -> None:
    """Счёт без договора дороже 1000 МРП — отправка запрещена (E-INV-01).
    Граница включительно: 4 325 000,00 можно, 4 325 000,01 нельзя (AC-005)."""
    limit = threshold(on_date)
    if money(amount_kzt) > limit:
        raise DomainError(
            "E-INV-01",
            f"Сумма счёта {fmt(amount_kzt, None)} тг превышает 1000 МРП "
            f"({fmt(limit, None)} тг). Оплата без договора невозможна. Оформите договор.",
            fields=[{"field": "amount", "message": "Больше 1000 МРП",
                     "threshold": str(limit)}])


# ── сумма в KZT (CALC-012, D-15) ────────────────────────────────────────

@dataclass(frozen=True)
class KztAmount:
    amount_kzt: Decimal
    rate: Decimal
    source: str  # "kzt" — документ в тенге; "nbrk" — курс НБРК на дату; "manual" — вручную


def to_kzt(amount, currency: str, on_date: date, *, manual_rate=None) -> KztAmount:
    """Сумма документа в KZT. Фактический курс (``manual_rate``) правится у
    счёта и у отметки оплаты (D-15); иначе — курс НБРК на дату документа."""
    if currency == KZT:
        return KztAmount(amount_kzt=money(amount), rate=Decimal("1"), source="kzt")
    if manual_rate is not None:
        rate, source = Decimal(manual_rate), "manual"
        if rate <= 0:
            raise DomainError("E-VAL-01", "Курс должен быть больше нуля.",
                              fields=[{"field": "rate", "message": "Курс > 0"}])
    else:
        rate, source = refdata.exchange_rate(currency, on_date), "nbrk"
        if rate is None:
            raise DomainError(
                "E-REF-05",
                f"Нет курса {currency} на {on_date:%d.%m.%Y}. Финансовый директор может "
                f"внести курс на эту дату в справочнике валют.",
                fields=[{"field": "rate", "message": "Нет курса на дату"}])
    return KztAmount(amount_kzt=money(Decimal(amount) * rate), rate=rate, source=source)


# ── остаток договора (CALC-009, BR-041) ─────────────────────────────────

def agreement_remaining(agreement_amount, invoiced) -> Decimal | None:
    """Сумма договора − Σ счетов по нему (кроме «Отменён» и «Не к оплате»);
    у открытого договора (суммы нет) — не рассчитывается."""
    if agreement_amount is None:
        return None
    return money(agreement_amount) - money(invoiced)


def check_agreement_remaining(*, agreement_number: str, agreement_amount, invoiced,
                              invoice_amount, currency: str = KZT) -> None:
    """BR-041: счёт по закрытому договору не больше его остатка (E-INV-02)."""
    remaining = agreement_remaining(agreement_amount, invoiced)
    if remaining is None:
        return
    over = money(invoice_amount) - remaining
    if over > 0:
        raise DomainError(
            "E-INV-02",
            f"Сумма счёта превышает остаток по договору {agreement_number} на "
            f"{fmt(over, currency)}. Уменьшите сумму или оформите дополнительное соглашение.",
            fields=[{"field": "amount", "message": "Больше остатка договора",
                     "remaining": str(remaining), "over": str(over)}])
