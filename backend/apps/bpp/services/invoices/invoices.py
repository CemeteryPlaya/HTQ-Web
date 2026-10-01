"""Счёт на оплату: черновик из плана или договора, «Отправить ФД», отмена,
колбэки решения ФД (ТЗ §10, §15.4, задача B3.2).

Отправка — одна транзакция: блокировка строки бюджета → сверхплановая часть
строк ≤ доступного остатка статьи (BR-043) → запуск ``signoff`` (один этап
ФД, D-12). Колбэк ``on_started`` переводит счёт в «На рассмотрении ФД» в той
же транзакции, и его строки сразу входят в «Задействовано».

Права — узел ``bpp.invoices`` (создают СН и ПМ, видят все роли модуля).
Правит счёт только автор и только в «Черновике» и «Возвращён на доработку»;
каждое изменение сначала спрашивает ``assert_editable``.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.utils import timezone

from apps.bpp.models import (
    Agreement,
    AgreementStatus,
    Invoice,
    InvoiceBasis,
    InvoiceLine,
    InvoiceStatus,
    PaymentMatchState,
    PurchaseRequestItem,
    RateSource,
)
from apps.bpp.services import calc
from apps.bpp.services.actor import Actor
from apps.bpp.services.alternatives import kpi, lifecycle
from apps.bpp.services.agreements import agreements as agreement_service
from apps.bpp.services.agreements import positions
from apps.bpp.services.budget import balance as budget_balance
from apps.bpp.services.budget import committed as committed_calc
from apps.bpp.services.core import audit
from apps.bpp.services.core import files as core_files
from apps.bpp.services.core.errors import check_version
from apps.bpp.services.core.numbering import next_number
from apps.bpp.services.counterparties import lookup as counterparties
from apps.bpp.services.money import fmt, money
from apps.bpp.services.plan import service as plan
from apps.bpp.services.selection import checks as selection_checks
from apps.signoff import interface as signoff
from htqweb.errors import DomainError

SUBJECT = Invoice.SIGNOFF_SUBJECT_TYPE
COMMENT_MIN = 10
EDITABLE = (InvoiceStatus.DRAFT, InvoiceStatus.RETURNED)
#: Срок оплаты по умолчанию — дата счёта + 5 рабочих дней (ТЗ §10.2 [У]).
DUE_WORKING_DAYS = 5
#: До решения ФД автор может отменить счёт сам (ТЗ §10.1).
BEFORE_DECISION = (InvoiceStatus.DRAFT, InvoiceStatus.RETURNED, InvoiceStatus.UNDER_REVIEW)

FIELD_LABELS = {
    "counterparty_id": "Контрагент",
    "ext_number": "Номер счёта контрагента",
    "ext_date": "Дата счёта контрагента",
    "amount": "Сумма счёта",
    "purchase_type": "Тип приобретения",
    "lines": "Строки счёта",
}


# ── права и видимость ───────────────────────────────────────────────────

def _deny(text: str) -> DomainError:
    return DomainError("E-ACC-01", f"{text} Если это ошибка, обратитесь к администратору.",
                       status=403)


def sees_all(actor: Actor) -> bool:
    """ФД, БУХ, ТД, ОД, ГД и АДМ видят все счета (ТЗ §10.1): у их ролей на
    ``bpp.invoices`` нет права создавать. Суперпользователь — тоже."""
    return actor.is_superuser or (actor.can("bpp.invoices", "view")
                                  and not actor.can("bpp.invoices", "create"))


def can_view(actor: Actor, inv: Invoice) -> bool:
    if inv.author_id == actor.user_id or sees_all(actor):
        return True
    return signoff.is_participant(actor.user_id, SUBJECT, str(inv.pk))


def get_visible(actor: Actor, invoice_id) -> Invoice:
    inv = Invoice.objects.filter(pk=invoice_id).first()
    if inv is None or not can_view(actor, inv):
        raise DomainError("E-NOT-FOUND", "Счёт не найден.", status=404)
    return inv


def lock(invoice_id) -> Invoice:
    inv = Invoice.objects.select_for_update().filter(pk=invoice_id).first()
    if inv is None:
        raise DomainError("E-NOT-FOUND", "Счёт не найден.", status=404)
    return inv


def _require_author(actor: Actor, inv: Invoice, action: str) -> None:
    if inv.author_id != actor.user_id:
        raise _deny(f"«{action}» доступно только автору счёта {inv.number}.")


def state_error(action: str, inv: Invoice) -> DomainError:
    return DomainError(
        "E-STS-01", f"Нельзя {action} счёт {inv.number} в статусе "
                    f"„{inv.get_status_display()}“.", status=409)


def require_status(inv: Invoice, statuses, action: str) -> None:
    if inv.status not in statuses:
        raise state_error(action, inv)


def comment_of(comment: str) -> str:
    comment = (comment or "").strip()
    if len(comment) < COMMENT_MIN:
        raise DomainError(
            "BR-060", "Опишите причину: комментарий не короче 10 символов.",
            fields=[{"field": "comment", "message": f"Минимум {COMMENT_MIN} символов"}])
    return comment


def touch(inv: Invoice, actor_id: int | None, *fields: str) -> None:
    inv.version += 1
    inv.updated_by = actor_id
    inv.save(update_fields=["version", "updated_by", "updated_at", *fields])


def allowed_actions(actor: Actor, inv: Invoice) -> list[str]:
    author = inv.author_id == actor.user_id
    fd = actor.can("bpp.invoices.decision", "edit")
    buh = actor.can("bpp.invoices.payment", "edit")
    actions = []
    if author and inv.status in EDITABLE:
        actions += ["save", "submit"]
        if inv.status == InvoiceStatus.DRAFT:
            actions.append("delete")
    # Черновик не отменяют, а удаляют: «Отменить» — для отправленного и
    # возвращённого счёта (у них уже есть номер в журнале и согласовании).
    if (author and inv.status in BEFORE_DECISION and inv.status != InvoiceStatus.DRAFT) or (
            fd and inv.status in (InvoiceStatus.UNDER_REVIEW, InvoiceStatus.TO_PAY)
            and not _has_payments(inv)):
        if inv.paid_bank_amount <= 0:
            actions.append("cancel")
    if fd and inv.status == InvoiceStatus.UNDER_REVIEW:
        actions += ["pay", "not_payable", "return"]
        if (inv.basis == InvoiceBasis.NO_CONTRACT
                and actor.can("bpp.alternatives.select", "edit")):
            actions.append("select_alternative")       # B5.1, ТЗ §12.4 п.3
    if buh and inv.status in (InvoiceStatus.TO_PAY, InvoiceStatus.PARTIALLY_PAID):
        actions.append("mark_paid")
    if buh and inv.status == InvoiceStatus.PAID:
        actions.append("request_docs")
    if (author or actor.can("bpp.invoices.closing_docs", "edit")) \
            and inv.status == InvoiceStatus.AWAITING_DOCS:
        actions.append("submit_docs")
    if buh and inv.status == InvoiceStatus.DOCS_PROVIDED:
        actions += ["accept_docs", "return_docs"]
    return actions


def qty_available(figures: dict, basis: str) -> Decimal:
    """Остаток количества позиции для строки счёта (CALC-005): счёт по договору
    берёт из остатка для счёта; счёт без договора — ещё и не больше того, что
    не держат договоры (позиции договора оплачиваются счетом по договору)."""
    if basis == InvoiceBasis.CONTRACT:
        return figures["qty_left_for_invoice"]
    return min(figures["qty_left"], figures["qty_left_for_invoice"])


def _has_payments(inv: Invoice) -> bool:
    return inv.payments.filter(cancelled_at__isnull=True).exists()


def _refuse_while_bank_paid(inv: Invoice) -> None:
    """Счёт, по которому сверка выписки держит деньги (``paid_bank_amount`` —
    действующие сопоставления, A4.2), не отменяется: отменённый счёт статью
    бюджета освобождает, а «Оплачено факт» и графики платёж продолжали бы
    считать. Выписка часто приходит раньше отметки БУХ, поэтому одной
    проверки отметок мало. То же правило, что у отмены отметки оплаты
    (``payments.unmark``); сопоставления «на проверку» в сумму не входят, а
    подтвердить их к отменённому счёту нельзя."""
    if inv.paid_bank_amount > 0:
        raise DomainError(
            "E-STATE-01", f"Нельзя отменить счёт {inv.number}: оплата по нему уже "
                          f"подтверждена выпиской банка. Сначала отмените сопоставление "
                          f"строки выписки.", status=409)


# ── расчёты ─────────────────────────────────────────────────────────────

def add_working_days(start: date, days: int) -> date:
    current = start
    while days > 0:
        current += timedelta(days=1)
        if current.weekday() < 5:
            days -= 1
    return current


def recalc(inv: Invoice) -> str | None:
    """НДС (CALC-008, D-14) и сумма в KZT (CALC-012, D-15). Возвращает
    предупреждение НДС для формы. Курса НБРК на дату нет — ``amount_kzt``
    пустая до отправки (там отказ ``E-REF-05``)."""
    warning = None
    on_date = inv.ext_date or timezone.localdate()
    if inv.agreement_id:
        agr = inv.agreement
        inv.with_vat, inv.vat_rate, inv.vat_source = agr.with_vat, agr.vat_rate, agr.vat_source
    elif not inv.with_vat:
        inv.vat_rate, inv.vat_source = None, ""
    elif inv.vat_source != "manual" and inv.counterparty_id:
        pick = calc.vat_for(inv.counterparty.country_code, on_date)
        inv.vat_rate, inv.vat_source, warning = pick.rate, pick.source, pick.warning
    inv.vat_amount = (calc.vat_amount(inv.amount, inv.vat_rate)
                      if inv.with_vat and inv.vat_rate is not None else None)
    if inv.currency_code == calc.KZT:
        inv.rate, inv.rate_source, inv.amount_kzt = Decimal("1"), RateSource.KZT, money(inv.amount)
    elif inv.rate_source == RateSource.MANUAL and inv.rate:
        inv.amount_kzt = calc.to_kzt(inv.amount, inv.currency_code, on_date,
                                     manual_rate=inv.rate).amount_kzt
    else:
        try:
            converted = calc.to_kzt(inv.amount, inv.currency_code, on_date)
            inv.rate, inv.rate_source, inv.amount_kzt = (converted.rate, RateSource.NBRK,
                                                         converted.amount_kzt)
        except DomainError:
            inv.rate, inv.rate_source, inv.amount_kzt = None, "", None
    return warning


def invoiced_by_agreement(agreement_ids, *, exclude_invoice_id=None) -> dict[str, Decimal]:
    """Σ счетов по договору, кроме «Отменён», «Не к оплате», «Заменён» (CALC-009)."""
    rows = (Invoice.objects.filter(agreement_id__in=list(agreement_ids))
            .exclude(status__in=positions.RELEASED_INVOICE_STATUSES))
    if exclude_invoice_id is not None:
        rows = rows.exclude(pk=exclude_invoice_id)
    return {str(row["agreement_id"]): row["total"] for row in
            rows.values("agreement_id").annotate(total=Sum("amount"))}


# ── черновик ────────────────────────────────────────────────────────────

def _snapshot(inv: Invoice) -> dict:
    return {
        "basis": inv.basis, "agreement_id": str(inv.agreement_id) if inv.agreement_id else None,
        "counterparty_id": str(inv.counterparty_id) if inv.counterparty_id else None,
        "ext_number": inv.ext_number,
        "ext_date": inv.ext_date.isoformat() if inv.ext_date else None,
        "amount": str(inv.amount), "currency_code": inv.currency_code,
        "rate": str(inv.rate) if inv.rate is not None else None, "rate_source": inv.rate_source,
        "with_vat": inv.with_vat,
        "vat_rate": str(inv.vat_rate) if inv.vat_rate is not None else None,
        "vat_source": inv.vat_source, "purchase_type": inv.purchase_type,
        "is_advance": inv.is_advance,
        "due_date": inv.due_date.isoformat() if inv.due_date else None,
        "lines": [{"item": line.request_item.sys_number, "qty": str(line.qty),
                   "amount": str(line.amount)}
                  for line in inv.lines.select_related("request_item").order_by("created_at")],
    }


def new_invoice(actor: Actor, *, rows: list[PurchaseRequestItem], agreement: Agreement | None,
                 quantities: dict[str, Decimal], amounts: dict[str, Decimal]) -> Invoice:
    today = timezone.localdate()
    request = rows[0].request
    inv = Invoice(
        number=next_number("СЧ"), author_id=actor.user_id,
        initiator_role=request.initiator_role,
        basis=InvoiceBasis.CONTRACT if agreement else InvoiceBasis.NO_CONTRACT,
        agreement=agreement, project_id=request.project_id, article_id=request.article_id,
        counterparty=agreement.counterparty if agreement else None,
        currency_code=agreement.currency_code if agreement else request.currency_code,
        purchase_type=(agreement.agreement_type if agreement else request.purchase_type) or "",
        ext_date=today, due_date=add_working_days(today, DUE_WORKING_DAYS),
        amount=money(sum(amounts.values(), Decimal("0"))),
        with_vat=agreement.with_vat if agreement else True,
        created_by=actor.user_id, updated_by=actor.user_id)
    recalc(inv)
    inv.save()
    for row in rows:
        key = str(row.pk)
        if quantities[key] <= 0 or amounts[key] <= 0:
            continue
        InvoiceLine.objects.create(invoice=inv, request_item=row, qty=quantities[key],
                                   amount=amounts[key], created_by=actor.user_id,
                                   updated_by=actor.user_id)
    return inv


@transaction.atomic
def create_from_plan(actor: Actor, item_ids: list[str], *, role: str | None = None) -> Invoice:
    """Счёт без договора из позиций плана (мастер F-03, ТЗ §8.4 шаг 1'):
    количество — остаток для счёта, сумма строки — остаток плановой суммы."""
    if not actor.can("bpp.invoices", "create"):
        raise _deny("Счета оформляют снабженцы и руководители проектов.")
    selection = plan.validate_selection(actor, item_ids, target="invoice", role=role)
    rows = list(PurchaseRequestItem.objects.select_related("request")
                .filter(pk__in=[row["id"] for row in selection["items"]]).order_by("sys_number"))
    left = positions.remaining(rows)
    inv = new_invoice(
        actor, rows=rows, agreement=None,
        quantities={str(r.pk): qty_available(left[str(r.pk)], InvoiceBasis.NO_CONTRACT)
                    for r in rows},
        amounts={str(r.pk): left[str(r.pk)]["amount_left"] for r in rows})
    audit.record(inv, "created", actor_id=actor.user_id,
                 changes={"items": [row.sys_number for row in rows]})
    return inv


@transaction.atomic
def create_from_agreement(actor: Actor, agreement_id, *, item_ids: list[str] | None = None
                          ) -> Invoice:
    """Счёт по действующему договору (ТЗ §9.4 «Создать счёт по договору»):
    контрагент, валюта, НДС и тип — из договора; строки — его позиции с
    остатком для счёта."""
    if not actor.can("bpp.invoices", "create"):
        raise _deny("Счета оформляют снабженцы и руководители проектов.")
    agr = agreement_service.get_visible(actor, agreement_id)
    if agr.status != AgreementStatus.ACTIVE or agr.parent_agreement_id is not None:
        raise DomainError(
            "BR-046", f"Счёт оформляется только по действующему договору; договор "
                      f"{agr.number} — „{agr.get_status_display()}“.", status=409)
    items = list(agr.items.select_related("request_item", "request_item__request"))
    if item_ids:
        wanted = {str(i) for i in item_ids}
        items = [i for i in items if str(i.request_item_id) in wanted]
    if not items:
        raise DomainError("E-VAL-01", "В договоре нет позиций для счёта.")
    rows = [i.request_item for i in items]
    left = positions.remaining(rows)
    quantities, amounts = {}, {}
    for item in items:
        key = str(item.request_item_id)
        quantities[key] = min(item.qty, left[key]["qty_left_for_invoice"])
        base = item.amount if item.amount is not None else item.request_item.amount
        amounts[key] = max(min(base, left[key]["amount_left"] or base), Decimal("0"))
    inv = new_invoice(actor, rows=rows, agreement=agr, quantities=quantities, amounts=amounts)
    audit.record(inv, "created", actor_id=actor.user_id,
                 changes={"agreement": agr.number, "items": [r.sys_number for r in rows]})
    return inv


_HEADER_FIELDS = ("ext_number", "ext_date", "amount", "currency_code", "with_vat",
                  "purchase_type", "is_advance", "due_date", "author_comment")


def _apply_lines(inv: Invoice, lines: list[dict], actor_id: int) -> None:
    current = {str(line.pk): line for line in inv.lines.select_related("request_item")}
    by_item = {str(line.request_item_id): line for line in current.values()}
    keep: set[str] = set()
    for row in lines:
        line = current.get(str(row.get("id") or "")) or by_item.get(
            str(row.get("request_item_id") or ""))
        if line is None:
            raise DomainError("E-VAL-01", "Строку в счёт добавляют из Плана закупок или договора.",
                              fields=[{"field": "lines", "message": "Неизвестная позиция"}])
        qty, amount = Decimal(str(row.get("qty") or 0)), money(row.get("amount") or 0)
        if qty <= 0 or amount <= 0:
            raise DomainError(
                "E-VAL-01", f"Количество и сумма строки {line.request_item.sys_number} — "
                            f"больше нуля.", fields=[{"field": "lines", "message": "> 0"}])
        line.qty, line.amount, line.updated_by = qty, amount, actor_id
        line.version += 1
        line.save(update_fields=["qty", "amount", "updated_by", "version", "updated_at"])
        keep.add(str(line.pk))
    inv.lines.exclude(pk__in=keep).delete()


@transaction.atomic
def update_draft(actor: Actor, invoice_id, *, expected_version: int | None,
                 data: dict) -> tuple[Invoice, str | None]:
    inv = lock(invoice_id)
    inv.assert_editable()
    _require_author(actor, inv, "Изменить")
    require_status(inv, EDITABLE, "изменить")
    check_version(inv, expected_version)
    before = _snapshot(inv)
    if data.get("basis") == InvoiceBasis.NO_CONTRACT and inv.agreement_id:
        # ТЗ §10.3 п.2: «По договору» → «Без договора» очищает договор.
        inv.basis, inv.agreement = InvoiceBasis.NO_CONTRACT, None
    if "counterparty_id" in data and inv.basis == InvoiceBasis.NO_CONTRACT:
        counterparty_id = data["counterparty_id"]
        inv.counterparty = (counterparties.assert_usable(counterparty_id)
                            if counterparty_id else None)
        inv.counterparty_confirmed = False
        if inv.counterparty is not None and "with_vat" not in data:
            inv.with_vat = inv.counterparty.is_vat_payer
    for key in _HEADER_FIELDS:
        if key in data and not (inv.agreement_id and key in ("currency_code", "with_vat",
                                                              "purchase_type")):
            setattr(inv, key, data[key])
    inv.amount = money(inv.amount or 0)
    if inv.ext_date and inv.ext_date > timezone.localdate():
        raise DomainError("E-VAL-01", "Дата счёта контрагента — не позже сегодняшней.",
                          fields=[{"field": "ext_date", "message": "≤ сегодня"}])
    if inv.due_date and inv.ext_date and inv.due_date < inv.ext_date:
        raise DomainError("E-VAL-01", "Срок оплаты — не раньше даты счёта.",
                          fields=[{"field": "due_date", "message": "≥ дата счёта"}])
    if "vat_rate" in data and not inv.agreement_id:
        if data["vat_rate"] is None:
            inv.vat_source = ""
        else:
            inv.vat_rate, inv.vat_source = Decimal(str(data["vat_rate"])), "manual"
    if "rate" in data:
        # Фактический курс транзакции (D-15); ``null`` — курс НБРК на дату.
        if data["rate"] is None:
            inv.rate_source = ""
        else:
            inv.rate, inv.rate_source = Decimal(str(data["rate"])), RateSource.MANUAL
    warning = recalc(inv)
    inv.save()
    if "lines" in data:
        _apply_lines(inv, data["lines"], actor.user_id)
    touch(inv, actor.user_id)
    audit.record(inv, "updated", actor_id=actor.user_id,
                 changes={"before": before, "after": _snapshot(inv)})
    return inv, warning


@transaction.atomic
def delete_draft(actor: Actor, invoice_id, *, expected_version: int | None) -> None:
    inv = lock(invoice_id)
    _require_author(actor, inv, "Удалить")
    require_status(inv, (InvoiceStatus.DRAFT,), "удалить")
    check_version(inv, expected_version)
    # Сверка выписки (A4.2, D-S4-3) сопоставляет платёж и с черновиком — «на
    # проверку». Такой черновик не удаляется, пока сопоставление не
    # отменено: строка выписки потеряла бы счёт, которому платила
    # (``PaymentMatch.invoice`` — PROTECT). Отменённые сопоставления уходят
    # вместе со счётом.
    matches = inv.payment_matches.all()
    if matches.exclude(state=PaymentMatchState.CANCELLED).exists():
        raise DomainError(
            "E-STATE-01",
            f"Счёт {inv.number} сопоставлен со строкой выписки банка — удалить его нельзя. "
            f"Отмените счёт или попросите финансового директора отменить сопоставление "
            f"в сверке выписки.",
            status=409)
    matches.delete()
    audit.record(inv, "deleted", actor_id=actor.user_id, changes={"number": inv.number})
    core_files.owner_deleted(inv, actor_id=actor.user_id)
    pk = inv.pk  # ``delete()`` обнуляет pk экземпляра
    inv.delete()
    kpi.sync_for_document("invoice", pk)  # удалённый новый счёт аннулирует KPI (A5.2)


# ── отправка ФД ─────────────────────────────────────────────────────────

def _check_required(inv: Invoice) -> None:
    missing = []
    if not inv.counterparty_id:
        missing.append("counterparty_id")
    if not inv.ext_number.strip():
        missing.append("ext_number")
    if not inv.ext_date:
        missing.append("ext_date")
    if inv.amount <= 0:
        missing.append("amount")
    if not inv.purchase_type:
        missing.append("purchase_type")
    if not inv.lines.exists():
        missing.append("lines")
    if missing:
        label = FIELD_LABELS[missing[0]]
        raise DomainError(
            "E-INV-05", f"Не удалось отправить счёт. Не заполнено поле „{label}“. "
                        f"Заполните поле и повторите отправку.",
            fields=[{"field": key, "message": "Обязательное поле"} for key in missing])


def _check_duplicate(inv: Invoice) -> None:
    """BR-045 / E-INV-03 — текст ТЗ §26.1."""
    other = (Invoice.objects
             .filter(counterparty_id=inv.counterparty_id, ext_number=inv.ext_number.strip(),
                     ext_date=inv.ext_date)
             .exclude(pk=inv.pk)
             .exclude(status__in=[InvoiceStatus.DRAFT, InvoiceStatus.RETURNED,
                                  *positions.RELEASED_INVOICE_STATUSES])
             .first())
    if other is not None:
        raise DomainError(
            "E-INV-03",
            f"Счёт № {inv.ext_number} от {inv.ext_date:%d.%m.%Y} "
            f"{counterparties.display_name(inv.counterparty)} уже зарегистрирован как "
            f"{other.number}. Откройте существующий счёт.",
            fields=[{"field": "ext_number", "message": "Дубль счёта",
                     "existing_id": str(other.pk)}])


def _check_agreement(inv: Invoice) -> None:
    """BR-046, BR-036, BR-041; текст расторжения — ТЗ §26.2."""
    agr = inv.agreement
    if agr.status == AgreementStatus.TERMINATED:
        when = timezone.localtime(agr.updated_at).strftime("%d.%m.%Y")
        raise DomainError("BR-046", f"Договор {agr.number} расторгнут {when}. Новые счета по "
                                    f"нему не оформляются.", status=409)
    if agr.status != AgreementStatus.ACTIVE or str(agr.project_id) != str(inv.project_id) \
            or str(agr.article_id) != str(inv.article_id):
        raise DomainError(
            "BR-046", f"Счёт по договору оформляется только по действующему договору того же "
                      f"проекта и статьи; договор {agr.number} — „{agr.get_status_display()}“.",
            status=409)
    if agr.valid_to and inv.ext_date and inv.ext_date > agr.valid_to:
        raise DomainError(
            "BR-036", f"Срок действия договора {agr.number} истёк {agr.valid_to:%d.%m.%Y}: "
                      f"дата счёта {inv.ext_date:%d.%m.%Y} позже. Оформите допсоглашение о "
                      f"продлении или новый договор.",
            fields=[{"field": "ext_date", "message": "Позже срока договора"}])
    calc.check_agreement_remaining(
        agreement_number=agr.number, agreement_amount=agreement_service.effective_amount(agr),
        invoiced=invoiced_by_agreement([str(agr.pk)], exclude_invoice_id=inv.pk).get(
            str(agr.pk), Decimal("0")),
        invoice_amount=inv.amount, currency=agr.currency_code)


def _check_lines(inv: Invoice) -> None:
    """BR-042 — количество ≤ остатка для счёта (CALC-005); BR-044 — Σ строк =
    сумме счёта."""
    lines = list(inv.lines.select_related("request_item"))
    left = positions.remaining([line.request_item for line in lines], exclude_invoice_id=inv.pk)
    for line in lines:
        available = qty_available(left[str(line.request_item_id)], inv.basis)
        if line.qty > available:
            raise DomainError(
                "BR-042",
                f"Остаток позиции {line.request_item.sys_number} изменился: доступно "
                f"{_qty(available)} вместо {_qty(line.qty)}. Обновите строки счёта.",
                status=409,
                fields=[{"field": "lines", "message": "Количество больше остатка",
                         "item_id": str(line.request_item_id), "available": str(available)}])
    total = money(sum((line.amount for line in lines), Decimal("0")))
    if total != money(inv.amount):
        raise DomainError(
            "BR-044", f"Сумма строк {fmt(total, inv.currency_code)} не равна сумме счёта "
                      f"{fmt(inv.amount, inv.currency_code)}. Исправьте строки или сумму.",
            fields=[{"field": "amount", "message": "Σ строк ≠ сумме счёта",
                     "lines_total": str(total)}])


def _qty(value: Decimal) -> str:
    return format(value.normalize(), "f").replace(".", ",")


def budget_delta(inv: Invoice) -> list[tuple[PurchaseRequestItem, Decimal]]:
    """На сколько этот счёт увеличит «Задействовано» по каждой позиции: строка
    сверх остатка плановой суммы, договоров и других счетов (BR-043). Сверка
    — по формуле CALC-002: ``max(план; Σ договоров; Σ счетов)``."""
    out = []
    for line in inv.lines.select_related("request_item"):
        item = line.request_item
        others = committed_calc.invoiced_for_item(item, exclude_invoice_id=inv.pk)
        agreements = committed_calc.agreements_for_item(item)
        before = max(item.amount, agreements, others)
        after = max(item.amount, agreements, others + line.amount)
        if after > before:
            out.append((item, after - before))
    return out


def check_budget(inv: Invoice, *, include_self: bool) -> dict:
    """Под блокировкой строки бюджета — BR-043 при отправке и повторно «на
    текущий момент» при «Оплатить» (ТЗ §26.2). ``include_self`` — счёт уже
    в «Задействовано» (на рассмотрении ФД): тогда достаточно, чтобы остаток не
    ушёл в минус."""
    budget_balance.lock_line(inv.project_id, inv.article_id)
    figures = budget_balance.balance(inv.project_id, inv.article_id)
    if include_self:
        if figures["available"] < 0:
            raise DomainError(
                "E-BUD-01",
                f"Бюджет статьи „{budget_balance.article_name(inv.article_id)}“ превышен на "
                f"{fmt(-figures['available'], inv.currency_code)}. Оплатить счёт {inv.number} "
                f"нельзя, пока лимит не скорректирован.",
                fields=[{"field": "amount", "message": "Бюджет превышен",
                         "available": str(figures["available"])}])
        return figures
    deltas = budget_delta(inv)
    over = sum((delta for _, delta in deltas), Decimal("0"))
    if over > figures["available"]:
        item, delta = deltas[0]
        raise DomainError(
            "BR-043",
            f"Счёт превышает план по позиции {item.sys_number} на "
            f"{fmt(delta, inv.currency_code)}, свободного остатка статьи "
            f"{fmt(figures['available'], inv.currency_code)} недостаточно.",
            fields=[{"field": "lines", "message": "Превышение над планом больше остатка",
                     "item_id": str(item.pk), "over": str(over),
                     "available": str(figures["available"])}])
    return figures


@transaction.atomic
def submit(actor: Actor, invoice_id, *, expected_version: int | None,
           counterparty_confirmed: bool = False) -> Invoice:
    """«Отправить ФД» (ТЗ §10.4): BR-040…046, контрагент, бюджет."""
    inv = lock(invoice_id)
    inv.assert_editable()
    _require_author(actor, inv, "Отправить ФД")
    require_status(inv, EDITABLE, "отправить")
    check_version(inv, expected_version)
    _check_required(inv)
    core_files.require_files(inv, action=f"отправить счёт {inv.number}")  # ТЗ §21
    counterparties.assert_usable(inv.counterparty_id)       # BR-030, E-CTR-01
    if (inv.basis == InvoiceBasis.NO_CONTRACT and not counterparty_confirmed
            and counterparties.needs_confirmation(inv.counterparty_id)):
        raise DomainError(
            "E-CTR-05",
            f"Контрагент {counterparties.display_name(inv.counterparty)} ещё не проверен. "
            f"Подтвердите, что реквизиты сверены с документами, и отправьте снова.",
            fields=[{"field": "counterparty_confirmed", "message": "Нужно подтверждение"}])
    recalc(inv)
    if inv.amount_kzt is None:
        calc.to_kzt(inv.amount, inv.currency_code, inv.ext_date)   # E-REF-05 с текстом
    if inv.basis == InvoiceBasis.NO_CONTRACT:
        calc.check_no_contract_threshold(inv.amount_kzt, inv.ext_date)   # BR-040, E-INV-01
    else:
        _check_agreement(inv)
    _check_duplicate(inv)
    _check_lines(inv)
    figures = check_budget(inv, include_self=False)
    # Новый счёт по АП: сумма в пределах 5 % от неё (ТЗ §12.4 п.5, B5.1).
    selection_checks.check_within_tolerance("invoice", inv, inv.amount_kzt)
    inv.counterparty_confirmed = inv.counterparty_confirmed or counterparty_confirmed
    inv.save()
    try:
        signoff.start_process(subject_type=SUBJECT, subject_id=str(inv.pk),
                              initiator_id=actor.user_id)
    except signoff.SignoffError as exc:
        raise DomainError("E-SGN-01", str(exc), status=409) from exc
    except IntegrityError as exc:
        raise DomainError("E-INV-03", "Счёт с этими номером и датой у контрагента уже "
                                      "зарегистрирован. Обновите страницу.", status=409) from exc
    inv.refresh_from_db()
    inv.status_comment = ""
    touch(inv, actor.user_id, "status_comment")
    changes = {"amount": str(inv.amount), "amount_kzt": str(inv.amount_kzt),
               "available_before": str(figures["available"])}
    if counterparty_confirmed:
        changes["counterparty_confirmed"] = counterparties.display_name(inv.counterparty)
    audit.record(inv, "submitted", actor_id=actor.user_id, changes=changes)
    return inv


def _process(inv: Invoice) -> dict | None:
    return signoff.get_process_for(SUBJECT, str(inv.pk))


@transaction.atomic
def cancel(actor: Actor, invoice_id, *, expected_version: int | None, comment: str) -> Invoice:
    """«Отменить счёт» (ТЗ §10.1): автор — до решения ФД, ФД — до первой
    отметки оплаты. Позиции освобождаются, резерв снят."""
    inv = lock(invoice_id)
    comment = comment_of(comment)
    check_version(inv, expected_version)
    fd = actor.can("bpp.invoices.decision", "edit")
    if inv.status in BEFORE_DECISION and inv.author_id == actor.user_id:
        pass
    elif fd and inv.status in (InvoiceStatus.UNDER_REVIEW, InvoiceStatus.TO_PAY):
        if _has_payments(inv):
            raise state_error("отменить", inv)
    elif inv.status in (*BEFORE_DECISION, InvoiceStatus.TO_PAY):
        raise _deny(f"Отменить счёт {inv.number} может автор до решения ФД или финансовый "
                    f"директор до оплаты.")
    else:
        raise state_error("отменить", inv)
    _refuse_while_bank_paid(inv)
    process = _process(inv)
    if process is not None and process["state"] == "pending":
        try:
            signoff.cancel_process(process_id=process["id"], actor_id=actor.user_id)
        except signoff.SignoffError as exc:
            raise DomainError("E-SGN-01", str(exc), status=409) from exc
        inv.refresh_from_db()
    inv.status, inv.status_comment = InvoiceStatus.CANCELLED, comment
    touch(inv, actor.user_id, "status", "status_comment")
    audit.record(inv, "cancelled", actor_id=actor.user_id, comment=comment)
    lifecycle.close_for_source("invoice", inv.pk, lifecycle.ANNULLED,
                               reason=lifecycle.REASON_INVOICE_CANCELLED)  # АП (A5.1)
    kpi.sync_for_document("invoice", inv.pk)  # KPI снабжения нового счёта (A5.2)
    return inv


# ── колбэки согласования (решение ФД, D-12) ─────────────────────────────

def on_started(invoice_id) -> None:
    Invoice.objects.filter(pk=invoice_id).update(status=InvoiceStatus.UNDER_REVIEW)
    lifecycle.notify_buyers("invoice", invoice_id)  # СН: можно предложить альтернативу (A5.1)
    kpi.sync_for_document("invoice", invoice_id)  # KPI — на отправленную сумму (A5.2)


def on_approved(invoice_id) -> None:
    """«Оплатить» → «К оплате»; плановая дата — то, что поставил ФД, иначе
    срок оплаты (решение из общего инбокса)."""
    inv = Invoice.objects.get(pk=invoice_id)
    Invoice.objects.filter(pk=invoice_id).update(
        status=InvoiceStatus.TO_PAY, fd_decided_at=timezone.now(), rework_comment="",
        planned_pay_date=inv.planned_pay_date or inv.due_date)
    lifecycle.close_for_source("invoice", invoice_id, lifecycle.NOT_SELECTED,
                               reason=lifecycle.REASON_INVOICE_PAY)  # АП (A5.1)


def on_rejected(invoice_id) -> None:
    Invoice.objects.filter(pk=invoice_id).update(status=InvoiceStatus.NOT_PAYABLE,
                                                fd_decided_at=timezone.now())
    lifecycle.close_for_source("invoice", invoice_id, lifecycle.ANNULLED,
                               reason=lifecycle.REASON_INVOICE_NOT_PAYABLE)  # АП (A5.1)
    kpi.sync_for_document("invoice", invoice_id)  # KPI снабжения нового счёта (A5.2)


def _last_comment(invoice_id, state: str) -> str:
    process = signoff.get_process_for(SUBJECT, str(invoice_id))
    comments = [task.get("comment") or "" for stage in (process or {}).get("stages", [])
                for task in stage["tasks"] if task["state"] == state]
    return comments[-1] if comments else ""


def on_rework(invoice_id) -> None:
    Invoice.objects.filter(pk=invoice_id).update(
        status=InvoiceStatus.RETURNED, fd_decided_at=timezone.now(),
        rework_comment=_last_comment(invoice_id, "rework"))
    lifecycle.close_for_source("invoice", invoice_id, lifecycle.ANNULLED,
                               reason=lifecycle.REASON_RETURNED)  # АП (A5.1)


def on_cancelled(invoice_id) -> None:
    # Отзыв идущего решения — это отмена счёта (``cancel``): статус ставит она.
    kpi.sync_for_document("invoice", invoice_id)


def check_requirement(invoice_id, key: str) -> str | None:
    """Этап ФД с ``requirement_key="bpp:budget"``: «Согласовать» из общего
    инбокса проходит ту же проверку бюджета «на текущий момент», что и
    доменная ручка «Оплатить» (ТЗ §26.2)."""
    if key != "bpp:budget":
        return None
    inv = Invoice.objects.filter(pk=invoice_id).first()
    if inv is None:
        return "счёт не найден"
    try:
        check_budget(inv, include_self=True)
    except DomainError as exc:
        return exc.message
    return None


def facts(invoice_id) -> dict:
    inv = Invoice.objects.filter(pk=invoice_id).first()
    if inv is None:
        return {}
    return {"amount": inv.amount, "amount_kzt": inv.amount_kzt or Decimal("0"),
            "currency": inv.currency_code, "basis": inv.basis,
            "purchase_type": inv.purchase_type, "is_advance": inv.is_advance}
