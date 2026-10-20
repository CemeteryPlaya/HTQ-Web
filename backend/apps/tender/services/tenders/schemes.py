"""Схемы оплаты тендера — шаблоны ТЗ «Оплата и доставка» (мастер-план T-15).

1 ``prepay`` — 100 % до отгрузки; 2 ``advance`` — X % до отгрузки и остаток
после приёмки; 3 ``postpay`` — 100 % после приёмки через N дней; 4
``staged`` (EPC) — после пилота: модель этапов есть, шаблона нет (422).
Сумма долей этапов — ровно 100.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from apps.tender.models import PaymentKind, PaymentScheme, PaymentStage, PaymentTrigger

from .ctx import bad

D = Decimal
HUNDRED = D("100")
PCT_STEP = D("0.01")
POSTPAY_DAYS_MAX = 365


def _pct(value) -> Decimal:
    if value is None or value == "":
        raise bad("advance_pct", "укажите долю аванса в процентах")
    try:
        pct = D(str(value)).quantize(PCT_STEP, rounding=ROUND_HALF_UP)
    except InvalidOperation:
        raise bad("advance_pct", "доля аванса — число") from None
    if not D("0") < pct < HUNDRED:
        raise bad("advance_pct", "доля аванса — больше 0 и меньше 100 %")
    return pct


def _days(value) -> int:
    if value is None or isinstance(value, bool):
        raise bad("postpay_days", "укажите срок оплаты в днях после приёмки")
    days = int(value)
    if not 1 <= days <= POSTPAY_DAYS_MAX:
        raise bad("postpay_days", f"срок оплаты — от 1 до {POSTPAY_DAYS_MAX} дней")
    return days


def from_template(kind: str, *, advance_pct=None, days=None) -> list[dict]:
    """Этапы схемы ``kind`` — ``[{order, trigger, pct, days}]``, сумма долей 100."""
    if kind == PaymentKind.PREPAY:
        stages = [(PaymentTrigger.BEFORE_SHIPMENT, HUNDRED, None)]
    elif kind == PaymentKind.ADVANCE:
        pct = _pct(advance_pct)
        stages = [(PaymentTrigger.BEFORE_SHIPMENT, pct, None),
                  (PaymentTrigger.ON_RECEIPT, HUNDRED - pct, None)]
    elif kind == PaymentKind.POSTPAY:
        stages = [(PaymentTrigger.ON_RECEIPT, HUNDRED, _days(days))]
    elif kind == PaymentKind.STAGED:
        raise bad("kind", "поэтапная оплата появится после пилота — выберите схему 1–3")
    else:
        raise bad("kind", "неизвестная схема оплаты")
    return [{"order": order, "trigger": str(trigger.value), "pct": pct, "days": d}
            for order, (trigger, pct, d) in enumerate(stages, start=1)]


def replace(tender, kind: str, *, advance_pct=None, postpay_days=None,
            actor_id: int) -> PaymentScheme:
    """Заменить желаемую схему тендера шаблоном (старая удаляется целиком)."""
    stages = from_template(kind, advance_pct=advance_pct, days=postpay_days)
    PaymentScheme.objects.filter(tender=tender).delete()
    scheme = PaymentScheme.objects.create(
        tender=tender, kind=kind,
        postpay_days=stages[0]["days"] if kind == PaymentKind.POSTPAY else None,
        created_by=actor_id, updated_by=actor_id)
    PaymentStage.objects.bulk_create([
        PaymentStage(scheme=scheme, created_by=actor_id, updated_by=actor_id, **stage)
        for stage in stages])
    return scheme


def out(scheme: PaymentScheme | None) -> dict | None:
    if scheme is None:
        return None
    return {"kind": scheme.kind, "postpay_days": scheme.postpay_days,
            "stages": [{"order": s.order, "trigger": s.trigger, "pct": str(s.pct),
                        "days": s.days} for s in scheme.stages.order_by("order")]}
