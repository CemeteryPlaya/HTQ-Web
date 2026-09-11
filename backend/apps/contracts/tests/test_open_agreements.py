"""Открытые (рамочные) договоры: суммы нет, а платить и считать бюджет надо.

Открытый договор хранится с ``amount = 0`` — «суммы ещё нет», а не «лимит
ноль». Тесты держат два следствия этого:

1. проверки «оплата не больше остатка договора» к нему не применяются —
   иначе по нему нельзя было бы заплатить ни тенге;
2. бюджет он расходует ОПЛАТАМИ, а не суммой — иначе 132 млн по бетону
   прошли бы мимо остатка программы. У стандартного договора — наоборот, и
   оплаты по нему к сумме договора не прибавляются.
"""

from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client

from apps.contracts.models import (
    AdvancePayment,
    AdvancePaymentStatus,
    AgreementType,
    CompletionAct,
    ContractPayment,
)
from apps.contracts.services import agreement_service, budget_calc
from apps.contracts.services.agreement_service import AgreementRuleViolation
from apps.signoff.models import ApprovalState

from .helpers import BASE, auth, make_agreement, make_line, token

pytestmark = pytest.mark.django_db


def _open_agreement(line=None, *, approved=True, amount="0.00", **over):
    agreement = make_agreement(line=line or make_line(), amount=amount,
                               contract_type=AgreementType.FRAMEWORK, **over)
    # Оплату заводят только по согласованному договору, а править можно
    # только НЕсогласованный (согласованный заперт до возврата на доработку)
    # — поэтому тестам правки нужен второй вариант.
    if approved:
        agreement.approval_state = ApprovalState.APPROVED
        agreement.save(update_fields=["approval_state"])
    return agreement


def _payment(agreement, amount, status=AdvancePaymentStatus.CLOSED):
    return ContractPayment.objects.create(
        administrator=agreement.budget_line.budget.administrator,
        agreement=agreement, amount=Decimal(amount), status=status,
    )


# ── Оплата по открытому договору возможна ───────────────────────────────

def test_payment_against_open_agreement_is_accepted(monkeypatch):
    # Раньше: «остаток договора» = 0 − 0, и любая оплата отклонялась.
    agreement = _open_agreement()
    monkeypatch.setattr(
        "apps.contracts.services.contract_payment_service.media.store_file",
        lambda **kwargs: {"id": "invoice-1"},
    )
    response = Client().post(f"{BASE}/contract-payments", {
        "administrator_id": str(agreement.budget_line.budget.administrator_id),
        "agreement_id": str(agreement.pk), "amount": "2538470.00",
        "invoice": SimpleUploadedFile("invoice.pdf", b"PDF"),
    }, **auth(token()))
    assert response.status_code == 201, response.content


def test_open_agreement_payment_over_budget_is_accepted_with_warning(monkeypatch):
    # Перерасход по открытому договору предупреждает, но не запрещает (так
    # решил заказчик): оплата создаётся, а в ответе — на сколько программа
    # уйдёт за лимит.
    agreement = _open_agreement(make_line(amount="1000000.00"))
    monkeypatch.setattr(
        "apps.contracts.services.contract_payment_service.media.store_file",
        lambda **kwargs: {"id": "invoice-1"},
    )
    response = Client().post(f"{BASE}/contract-payments", {
        "administrator_id": str(agreement.budget_line.budget.administrator_id),
        "agreement_id": str(agreement.pk), "amount": "1500000.00",
        "invoice": SimpleUploadedFile("invoice.pdf", b"PDF"),
    }, **auth(token()))

    assert response.status_code == 201, response.content
    assert response.json()["budget_overrun"] == "500000.00"
    detail = Client().get(f"{BASE}/contract-payments/{response.json()['id']}", **auth(token()))
    assert detail.json()["budget_overrun"] == "500000.00"


def test_budget_overrun_is_not_counted_twice_once_payment_is_spending():
    # До одобрения оплата в остатке строки не сидит — вычитается сама; после
    # одобрения уже сидит, и второй раз её вычитать нельзя.
    line = make_line(amount="1000000.00")
    agreement = _open_agreement(line)
    draft = _payment(agreement, "1500000.00", AdvancePaymentStatus.DRAFT)
    assert budget_calc.open_payment_overrun(draft) == Decimal("500000.00")

    draft.status = AdvancePaymentStatus.CLOSED
    draft.save(update_fields=["status"])
    assert budget_calc.open_payment_overrun(draft) == Decimal("500000.00")


def test_no_budget_warning_within_limit_or_for_standard_agreement():
    line = make_line(amount="1000000.00")
    open_agreement = _open_agreement(line)
    within = _payment(open_agreement, "300000.00", AdvancePaymentStatus.DRAFT)
    # Стандартный договор охраняет бюджет своей суммой; его оплаты строку
    # не занимают, и предупреждать по ним не о чем.
    standard = make_agreement(line=line, amount="500000.00", number="Д-002",
                              counterparty=open_agreement.counterparty)
    big = _payment(standard, "500000.00", AdvancePaymentStatus.DRAFT)

    assert budget_calc.open_payment_overrun(within) is None
    assert budget_calc.open_payment_overrun(big) is None


def test_editing_open_agreement_with_payments_is_allowed():
    # Правка названия не должна падать на «сумма меньше оплаченного»:
    # у открытого договора оплаты больше нуля всегда.
    agreement = _open_agreement(approved=False)
    _payment(agreement, "300000.00")

    updated = agreement_service.update_agreement(agreement.pk, name="ГСМ по талонам")

    assert updated.name == "ГСМ по талонам"


def test_switching_open_to_standard_must_cover_paid_amount():
    # Перевод в стандартный — ровно тот момент, когда сумма появляется, и
    # она обязана покрыть уже оплаченное.
    agreement = _open_agreement(approved=False)
    _payment(agreement, "300000.00")

    with pytest.raises(AgreementRuleViolation, match="меньше уже проведённых"):
        agreement_service.update_agreement(
            agreement.pk, contract_type=AgreementType.STANDARD, amount=Decimal("100000.00"),
        )


# ── Бюджет видит расход по открытому договору ───────────────────────────

def test_budget_counts_open_agreement_payments_from_approval_on():
    line = make_line(amount="1000000.00")
    agreement = _open_agreement(line)
    _payment(agreement, "300000.00", AdvancePaymentStatus.CLOSED)
    _payment(agreement, "999999.00", AdvancePaymentStatus.DRAFT)       # не считается
    _payment(agreement, "999999.00", AdvancePaymentStatus.ON_REVIEW)   # не считается
    AdvancePayment.objects.create(agreement=agreement, amount=Decimal("100000.00"),
                                  status=AdvancePaymentStatus.AWAITING_ACCOUNTING)
    CompletionAct.objects.create(
        administrator=line.budget.administrator, agreement=agreement,
        amount=Decimal("50000.00"), status=AdvancePaymentStatus.CLOSED,
    )

    assert budget_calc.committed_for(line.pk) == Decimal("450000.00")
    assert budget_calc.remaining_for(line) == Decimal("550000.00")


def test_standard_agreement_payments_are_not_counted_twice():
    # Сумма стандартного договора уже заняла бюджет целиком — оплата по нему
    # тратит те же деньги, а не новые.
    line = make_line(amount="1000000.00")
    agreement = make_agreement(line=line, amount="400000.00")
    _payment(agreement, "100000.00")

    assert budget_calc.committed_for(line.pk) == Decimal("400000.00")


def test_standard_agreement_cannot_shrink_below_paid():
    line = make_line(amount="1000000.00")
    agreement = make_agreement(line=line, amount="400000.00", status="draft")
    _payment(agreement, "300000.00")

    with pytest.raises(AgreementRuleViolation):
        agreement_service.update_agreement(agreement.pk, amount=Decimal("200000.00"))
    # А вырасти — может: оплаченное новая сумма покрывает.
    grown = agreement_service.update_agreement(agreement.pk, amount=Decimal("500000.00"))
    assert grown.amount == Decimal("500000.00")


def test_open_agreement_has_no_remaining_amount_limit():
    # «0 − оплачено» дало бы отрицательный остаток, и формы оплаты сочли бы,
    # что платить нечего. У открытого договора остатка нет вовсе.
    open_agreement = _open_agreement()
    _payment(open_agreement, "300000.00")
    # Та же строка и тот же контрагент: тест про РАСЧЁТ остатка в карточке,
    # а не про изоляцию строк. Вторые ``make_line()``/``make_counterparty()``
    # с умолчаниями упёрлись бы в ключ бескодовой программы и в БИН.
    standard = make_agreement(line=open_agreement.budget_line,
                              counterparty=open_agreement.counterparty,
                              amount="400000.00", number="Д-002")
    _payment(standard, "100000.00")

    open_card = agreement_service.serialize_agreement(open_agreement)
    standard_card = agreement_service.serialize_agreement(standard)

    assert open_card["remaining_amount"] is None
    assert open_card["contract_paid_amount"] == Decimal("300000.00")
    assert standard_card["remaining_amount"] == Decimal("300000.00")


def test_open_agreement_card_through_api():
    agreement = _open_agreement()
    response = Client().get(f"{BASE}/agreements/{agreement.pk}", **auth(token()))

    assert response.status_code == 200, response.content
    assert response.json()["remaining_amount"] is None
    assert response.json()["contract_type"] == "framework"


def test_open_agreement_with_amount_is_counted_by_payments_only():
    # В реестре бывает открытый договор с проставленной суммой (у
    # DOC-00050-20260806 — 1 550 000). Расход по нему — оплаты; посчитай
    # ещё и сумму — одни и те же деньги легли бы в строку дважды.
    line = make_line(amount="5000000.00")
    agreement = _open_agreement(line, amount="1550000.00")
    _payment(agreement, "1250000.00")

    assert budget_calc.committed_for(line.pk) == Decimal("1250000.00")


def test_open_agreement_amount_does_not_hit_budget_check():
    # Лимит проверяется на то, что договор займёт, а открытый договор суммой
    # не займёт ничего: его сумма больше остатка строки — не повод не
    # пустить его в занимающий статус.
    line = make_line(amount="1000000.00")
    agreement = _open_agreement(line, approved=False, status="draft",
                                amount="5000000.00")

    moved = agreement_service.change_status(agreement.pk, "on_review")

    assert moved.status == "on_review"
    assert budget_calc.committed_for(line.pk) == Decimal("0.00")


def test_terminated_open_agreement_keeps_its_spending():
    # Расторжение не возвращает уже потраченных денег.
    line = make_line(amount="1000000.00")
    agreement = _open_agreement(line, status="terminated")
    _payment(agreement, "250000.00")

    assert budget_calc.committed_for(line.pk) == Decimal("250000.00")
