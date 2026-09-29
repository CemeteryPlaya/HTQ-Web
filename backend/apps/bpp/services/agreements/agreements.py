"""Договор: черновик из плана, отправка, отзыв, «Исполнен», расторжение,
допсоглашение (ТЗ §09, §15.3, задача B3.1).

Отправка — одна транзакция: блокировка строки бюджета → превышение над
планом позиций ≤ доступного остатка статьи (BR-034) → запуск ``signoff``.
Колбэк ``on_started`` переводит договор в «На согласовании» в той же
транзакции, поэтому вторая отправка, ждавшая блокировку строки, увидит
первую уже в «Задействовано».

Права — узел ``bpp.agreements`` (создают СН и ПМ, видят все роли модуля),
расторжение и «Исполнен» — ``bpp.agreements.terminate`` (ФД). Правит договор
только автор и только в «Черновике» и «На доработке»; каждое изменение
сначала спрашивает ``assert_editable`` (замок согласования, CLAUDE.md).
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.utils import timezone

from apps.bpp.models import (
    Agreement,
    AgreementItem,
    AgreementStatus,
    AgreementType,
    Invoice,
    InvoiceStatus,
    PurchaseRequestItem,
    VatSource,
)
from apps.bpp.services import calc
from apps.bpp.services.actor import Actor
from apps.bpp.services.budget import balance as budget_balance
from apps.bpp.services.core import audit
from apps.bpp.services.core.errors import check_version
from apps.bpp.services.core.numbering import next_number
from apps.bpp.services.counterparties import lookup as counterparties
from apps.bpp.services.money import fmt, money
from apps.bpp.services.plan import service as plan
from apps.project import interface as projects
from apps.refdata import interface as refdata
from apps.signoff import interface as signoff
from htqweb.errors import DomainError

from . import positions

SUBJECT = Agreement.SIGNOFF_SUBJECT_TYPE
SUPPLEMENTARY = "supplementary"
COMMENT_MIN = 10
NAME_MIN, NAME_MAX = 3, 500
EDITABLE = (AgreementStatus.DRAFT, AgreementStatus.REWORK)
#: Дата договора — не позже сегодня + 30 дней [У] и не раньше 2020 года (ТЗ §9.2).
FUTURE_DAYS = 30
EARLIEST = date(2020, 1, 1)

#: Подписи обязательных полей отказа при отправке.
FIELD_LABELS = {
    "counterparty_id": "Контрагент",
    "name": "Наименование договора",
    "ext_number": "Номер договора",
    "ext_date": "Дата договора",
    "agreement_type": "Тип договора",
    "amount": "Сумма договора",
    "items": "Позиции договора",
}


# ── права и видимость ───────────────────────────────────────────────────

def _deny(text: str) -> DomainError:
    return DomainError("E-ACC-01", f"{text} Если это ошибка, обратитесь к администратору.",
                       status=403)


def sees_all(actor: Actor) -> bool:
    """ФД, ТД, ОД, ГД, БУХ и АДМ видят все договоры (ТЗ §9.1): у их ролей на
    ``bpp.agreements`` нет права создавать."""
    return actor.can("bpp.agreements", "view") and not actor.can("bpp.agreements", "create")


def _sees_by_scope(actor: Actor, agr: Agreement) -> bool:
    """СН и ПМ видят договоры своих проектов и групп статей — они нужны для
    счетов (ТЗ §9.1 [Л])."""
    if not actor.can("bpp.agreements", "view") or not actor.sees_project(agr.project_id):
        return False
    brief = refdata.article_brief([str(agr.article_id)]).get(str(agr.article_id))
    return actor.sees_article(brief)


def can_view(actor: Actor, agr: Agreement) -> bool:
    if agr.author_id == actor.user_id or sees_all(actor) or _sees_by_scope(actor, agr):
        return True
    # Согласующий видит то, что согласует, даже без роли в модуле.
    return signoff.is_participant(actor.user_id, SUBJECT, str(agr.pk))


def get_visible(actor: Actor, agreement_id) -> Agreement:
    agr = Agreement.objects.filter(pk=agreement_id).first()
    if agr is None or not can_view(actor, agr):
        raise DomainError("E-NOT-FOUND", "Договор не найден.", status=404)
    return agr


def _lock(agreement_id) -> Agreement:
    agr = Agreement.objects.select_for_update().filter(pk=agreement_id).first()
    if agr is None:
        raise DomainError("E-NOT-FOUND", "Договор не найден.", status=404)
    return agr


def _require_author(actor: Actor, agr: Agreement, action: str) -> None:
    if agr.author_id != actor.user_id:
        raise _deny(f"«{action}» доступно только автору договора {agr.number}.")


def _state_error(action: str, agr: Agreement) -> DomainError:
    return DomainError(
        "E-STS-01", f"Нельзя {action} договор {agr.number} в статусе "
                    f"„{agr.get_status_display()}“.", status=409)


def _require_status(agr: Agreement, statuses, action: str) -> None:
    if agr.status not in statuses:
        raise _state_error(action, agr)


def _process(agr: Agreement) -> dict | None:
    return signoff.get_process_for(SUBJECT, str(agr.pk))


def _has_decisions(agr: Agreement) -> bool:
    process = _process(agr)
    if process is None or process["state"] != "pending":
        return False
    return any(task["state"] in ("approved", "rejected", "rework")
               for stage in process["stages"] for task in stage["tasks"])


def allowed_actions(actor: Actor, agr: Agreement) -> list[str]:
    author = agr.author_id == actor.user_id
    actions = []
    if author and agr.status in EDITABLE:
        actions += ["save", "submit"]
        if agr.status == AgreementStatus.DRAFT:
            actions.append("delete")
    if author and agr.status == AgreementStatus.ON_REVIEW and not _has_decisions(agr):
        actions.append("withdraw")
    if agr.status == AgreementStatus.ACTIVE:
        if actor.can("bpp.agreements.terminate", "edit"):
            actions += ["fulfil", "terminate"]
        if agr.parent_agreement_id is None and actor.can("bpp.agreements", "create"):
            actions.append("supplement")
        if agr.parent_agreement_id is None and actor.can("bpp.invoices", "create"):
            actions.append("create_invoice")
    actions.append("print")
    return actions


# ── расчёты ─────────────────────────────────────────────────────────────

def effective_amount(agr: Agreement) -> Decimal | None:
    """Сумма договора для остатка (CALC-009): сумма плюс утверждённые
    допсоглашения (D-18, суммы складываются); у открытого — ``None``."""
    if agr.is_open or agr.amount is None:
        return None
    extra = (Agreement.objects.filter(parent_agreement=agr, status=AgreementStatus.ACTIVE)
             .aggregate(total=Sum("amount"))["total"]) or Decimal("0")
    return money(agr.amount + extra)


def _recalc_vat(agr: Agreement) -> str | None:
    """НДС по D-14: ставка страны контрагента на дату договора из справочника;
    нет ставки — 16% с предупреждением; ручная ставка не перетирается.
    Возвращает предупреждение для формы (или ``None``)."""
    warning = None
    if not agr.with_vat:
        agr.vat_rate, agr.vat_source, agr.vat_amount = None, "", None
        return None
    if agr.vat_source != VatSource.MANUAL and agr.counterparty_id:
        pick = calc.vat_for(agr.counterparty.country_code, agr.ext_date or timezone.localdate())
        agr.vat_rate = pick.rate
        agr.vat_source = VatSource.REFDATA if pick.source == "refdata" else VatSource.DEFAULT
        warning = pick.warning
    agr.vat_amount = (calc.vat_amount(agr.amount, agr.vat_rate)
                      if agr.amount is not None and agr.vat_rate is not None else None)
    return warning


def _plan_item_rows(item_ids) -> list[PurchaseRequestItem]:
    return list(PurchaseRequestItem.objects.select_related("request")
                .filter(pk__in=list(item_ids)).order_by("sys_number"))


# ── черновик ────────────────────────────────────────────────────────────

def _touch(agr: Agreement, actor_id: int, *fields: str) -> None:
    agr.version += 1
    agr.updated_by = actor_id
    agr.save(update_fields=["version", "updated_by", "updated_at", *fields])


def _snapshot(agr: Agreement) -> dict:
    return {
        "counterparty_id": str(agr.counterparty_id) if agr.counterparty_id else None,
        "name": agr.name, "ext_number": agr.ext_number,
        "ext_date": agr.ext_date.isoformat() if agr.ext_date else None,
        "agreement_type": agr.agreement_type, "is_open": agr.is_open,
        "amount": str(agr.amount) if agr.amount is not None else None,
        "with_vat": agr.with_vat,
        "vat_rate": str(agr.vat_rate) if agr.vat_rate is not None else None,
        "vat_source": agr.vat_source,
        "valid_to": agr.valid_to.isoformat() if agr.valid_to else None,
        "items": [{"item": i.request_item.sys_number, "qty": str(i.qty),
                   "amount": str(i.amount) if i.amount is not None else None}
                  for i in agr.items.select_related("request_item").order_by("created_at")],
    }


@transaction.atomic
def create_from_plan(actor: Actor, item_ids: list[str], *, role: str | None = None
                     ) -> Agreement:
    """Черновик договора из позиций плана (мастер F-03, ТЗ §8.4): проект,
    статья и тип — из заявки, количество — остаток позиции, сумма по
    умолчанию — Σ остатков плановых сумм (ТЗ §9.2)."""
    if not actor.can("bpp.agreements", "create"):
        raise _deny("Договоры оформляют снабженцы и руководители проектов.")
    selection = plan.validate_selection(actor, item_ids, target="contract", role=role)
    rows = _plan_item_rows(row["id"] for row in selection["items"])
    left = positions.remaining(rows)
    amounts = {str(row.pk): min(left[str(row.pk)]["amount_left"], row.amount) for row in rows}
    project = projects.project_brief([selection["project_id"]]).get(selection["project_id"]) or {}
    kind = selection["purchase_type"] or ""
    kind_label = {"goods": "ТМЦ", "works": "работы и услуги"}.get(kind, "закупку")
    agr = Agreement.objects.create(
        number=next_number("ДГ"), author_id=actor.user_id,
        initiator_role=rows[0].request.initiator_role,
        project_id=selection["project_id"], article_id=selection["article_id"],
        agreement_type=kind, ext_date=timezone.localdate(),
        name=f"Договор на {kind_label} по проекту {project.get('code', '')}".strip(),
        amount=money(sum(amounts.values(), Decimal("0"))),
        currency_code=rows[0].request.currency_code,
        created_by=actor.user_id, updated_by=actor.user_id)
    for row in rows:
        AgreementItem.objects.create(agreement=agr, request_item=row,
                                     qty=left[str(row.pk)]["qty_left"],
                                     amount=amounts[str(row.pk)], created_by=actor.user_id,
                                     updated_by=actor.user_id)
    audit.record(agr, "created", actor_id=actor.user_id,
                 changes={"items": [row.sys_number for row in rows]})
    return agr


def _clean_date(value, field: str, label: str):
    if value is None:
        return None
    today = timezone.localdate()
    if value < EARLIEST or value > today + timedelta(days=FUTURE_DAYS):
        raise DomainError(
            "E-VAL-01", f"{label}: не раньше 01.01.2020 и не позже чем через {FUTURE_DAYS} "
                        f"дней от сегодняшнего дня.",
            fields=[{"field": field, "message": "Дата вне допустимого диапазона"}])
    return value


def _apply_items(agr: Agreement, items: list[dict], actor_id: int) -> None:
    """Количество и сумма позиций; добавить позицию можно только из плана,
    убрать — да (ТЗ §9.2 «Позиции договора»). Количество ≤ остатка (BR-042)."""
    current = {str(i.pk): i for i in agr.items.select_related("request_item")}
    by_request_item = {str(i.request_item_id): i for i in current.values()}
    keep: set[str] = set()
    for row in items:
        key = str(row.get("id") or "")
        item = current.get(key) or by_request_item.get(str(row.get("request_item_id") or ""))
        if item is None:
            raise DomainError("E-VAL-01", "Позицию в договор добавляют из Плана закупок.",
                              fields=[{"field": "items", "message": "Неизвестная позиция"}])
        qty = Decimal(str(row.get("qty") or 0))
        if qty <= 0:
            raise DomainError(
                "E-VAL-01", f"Количество по позиции {item.request_item.sys_number} — больше нуля.",
                fields=[{"field": "items", "message": "Количество > 0"}])
        amount = row.get("amount")
        item.qty = qty
        item.amount = None if agr.is_open or amount is None else money(amount)
        item.updated_by = actor_id
        item.version += 1
        item.save(update_fields=["qty", "amount", "updated_by", "version", "updated_at"])
        keep.add(str(item.pk))
    agr.items.exclude(pk__in=keep).delete()
    _check_remaining(agr)


def _check_remaining(agr: Agreement) -> None:
    """BR-042: количество позиции ≤ остатка (CALC-005) на момент сохранения;
    текст — ТЗ §26.2."""
    items = list(agr.items.select_related("request_item"))
    left = positions.remaining([i.request_item for i in items], exclude_agreement_id=agr.pk)
    for item in items:
        available = left[str(item.request_item_id)]["qty_left"]
        if item.qty > available:
            raise DomainError(
                "BR-042",
                f"Остаток позиции {item.request_item.sys_number} изменился: доступно "
                f"{_qty(available)} вместо {_qty(item.qty)}. Обновите позиции договора.",
                status=409,
                fields=[{"field": "items", "message": "Количество больше остатка",
                         "item_id": str(item.request_item_id), "available": str(available)}])


def _qty(value: Decimal) -> str:
    text = format(value.normalize(), "f")
    return text.replace(".", ",")


_HEADER_FIELDS = ("name", "ext_number", "ext_date", "agreement_type", "is_open", "amount",
                  "currency_code", "with_vat", "valid_to")


@transaction.atomic
def update_draft(actor: Actor, agreement_id, *, expected_version: int | None,
                 data: dict) -> tuple[Agreement, str | None]:
    """Правка автором в «Черновике» и «На доработке». Возвращает договор и
    предупреждение НДС (D-14: ставки на дату нет — подставлено 16%)."""
    agr = _lock(agreement_id)
    agr.assert_editable()
    _require_author(actor, agr, "Изменить")
    _require_status(agr, EDITABLE, "изменить")
    check_version(agr, expected_version)
    before = _snapshot(agr)
    if "counterparty_id" in data:
        counterparty_id = data["counterparty_id"]
        agr.counterparty = (counterparties.assert_usable(counterparty_id)
                            if counterparty_id else None)
        agr.counterparty_confirmed = False
        if agr.counterparty is not None and "with_vat" not in data:
            agr.with_vat = agr.counterparty.is_vat_payer
    for key in _HEADER_FIELDS:
        if key in data:
            setattr(agr, key, data[key])
    if "name" in data and agr.name and not NAME_MIN <= len(agr.name.strip()) <= NAME_MAX:
        raise DomainError("E-VAL-01", "Наименование договора — от 3 до 500 символов.",
                          fields=[{"field": "name", "message": "3–500 символов"}])
    agr.ext_date = _clean_date(agr.ext_date, "ext_date", "Дата договора")
    if agr.is_open:
        agr.amount = None
    elif agr.amount is not None:
        agr.amount = money(agr.amount)
        if agr.amount < 0:
            raise DomainError("E-VAL-01", "Сумма договора не может быть отрицательной.",
                              fields=[{"field": "amount", "message": "Сумма ≥ 0"}])
    if "vat_rate" in data:
        # Ручная ставка (D-14) — любой автор или согласующий; ``null`` —
        # вернуть ставку из справочника.
        if data["vat_rate"] is None:
            agr.vat_source = ""
        else:
            agr.vat_rate, agr.vat_source = Decimal(str(data["vat_rate"])), VatSource.MANUAL
    warning = _recalc_vat(agr)
    agr.save()
    if "items" in data:
        _apply_items(agr, data["items"], actor.user_id)
    if agr.is_open:
        agr.items.update(amount=None)
    _touch(agr, actor.user_id)
    audit.record(agr, "updated", actor_id=actor.user_id,
                 changes={"before": before, "after": _snapshot(agr)})
    return agr, warning


@transaction.atomic
def delete_draft(actor: Actor, agreement_id, *, expected_version: int | None) -> None:
    """Удаление — автор, только «Черновик»; позиции освобождаются (ТЗ §9.4)."""
    agr = _lock(agreement_id)
    _require_author(actor, agr, "Удалить")
    _require_status(agr, (AgreementStatus.DRAFT,), "удалить")
    check_version(agr, expected_version)
    audit.record(agr, "deleted", actor_id=actor.user_id, changes={"number": agr.number})
    agr.delete()


# ── отправка ────────────────────────────────────────────────────────────

def _missing(agr: Agreement) -> list[str]:
    missing = []
    if not agr.counterparty_id:
        missing.append("counterparty_id")
    if not (agr.name or "").strip():
        missing.append("name")
    if not agr.ext_number.strip():
        missing.append("ext_number")
    if not agr.ext_date:
        missing.append("ext_date")
    if not agr.agreement_type:
        missing.append("agreement_type")
    supplement = agr.parent_agreement_id is not None
    if not agr.is_open and (agr.amount is None or (agr.amount <= 0 and not supplement)):
        missing.append("amount")
    if not supplement and not agr.items.exists():
        missing.append("items")   # D-19: хотя бы одна позиция
    return missing


def _check_required(agr: Agreement) -> None:
    missing = _missing(agr)
    if missing:
        label = FIELD_LABELS[missing[0]]
        raise DomainError(
            "E-AGR-01", f"Не удалось отправить договор. Не заполнено поле „{label}“. "
                        f"Заполните поле и повторите отправку.",
            fields=[{"field": key, "message": "Обязательное поле"} for key in missing])


def _check_duplicate(agr: Agreement) -> None:
    """BR-032: контрагент + номер + дата по документу уникальны."""
    other = (Agreement.objects
             .filter(counterparty_id=agr.counterparty_id, ext_number=agr.ext_number.strip(),
                     ext_date=agr.ext_date)
             .exclude(pk=agr.pk)
             .exclude(status__in=[AgreementStatus.REJECTED, AgreementStatus.REPLACED,
                                  AgreementStatus.DRAFT, AgreementStatus.REWORK])
             .first())
    if other is not None:
        raise DomainError(
            "BR-032",
            f"Договор № {agr.ext_number} от {agr.ext_date:%d.%m.%Y} с "
            f"{counterparties.display_name(agr.counterparty)} уже зарегистрирован: "
            f"{other.number}. Откройте существующий договор.",
            fields=[{"field": "ext_number", "message": "Дубль договора",
                     "existing_id": str(other.pk)}])


def _check_sum(agr: Agreement) -> None:
    """BR-033: у закрытого договора Σ сумм позиций = сумме договора."""
    if agr.is_open or agr.parent_agreement_id is not None:
        return
    total = money(agr.items.aggregate(total=Sum("amount"))["total"] or 0)
    if total != agr.amount:
        raise DomainError(
            "BR-033",
            f"Сумма позиций {fmt(total, agr.currency_code)} не равна сумме договора "
            f"{fmt(agr.amount, agr.currency_code)}. Исправьте суммы позиций или договора.",
            fields=[{"field": "amount", "message": "Σ позиций ≠ сумме договора",
                     "items_total": str(total)}])


def _plan_total(agr: Agreement) -> Decimal:
    return money(sum((i.request_item.amount for i in agr.items.select_related("request_item")),
                     Decimal("0")))


def over_plan(agr: Agreement) -> Decimal:
    """Превышение договора над планом позиций (BR-034); у допсоглашения — весь
    прирост суммы: лимиты идут на общие суммы договоров (D-18, В-05)."""
    if agr.is_open or agr.amount is None:
        return Decimal("0")
    if agr.parent_agreement_id is not None:
        return agr.amount
    return max(agr.amount - _plan_total(agr), Decimal("0"))


def _check_budget(agr: Agreement) -> dict:
    """Под блокировкой строки бюджета: превышение над планом ≤ доступного
    остатка статьи (BR-034, ТЗ §9.3 п.5)."""
    budget_balance.lock_line(agr.project_id, agr.article_id)
    figures = budget_balance.balance(agr.project_id, agr.article_id)
    over = over_plan(agr)
    if over > figures["available"]:
        raise DomainError(
            "BR-034",
            f"Сумма договора превышает план позиций на {fmt(over, agr.currency_code)}, "
            f"свободного остатка статьи „{budget_balance.article_name(agr.article_id)}“ "
            f"{fmt(figures['available'], agr.currency_code)} недостаточно. Уменьшите сумму "
            f"или обратитесь к финансовому директору за корректировкой лимита.",
            fields=[{"field": "amount", "message": "Превышение над планом больше остатка",
                     "over": str(over), "available": str(figures["available"])}])
    return figures


def _signoff_error(exc: Exception) -> DomainError:
    return DomainError("E-SGN-01", str(exc), status=409)


@transaction.atomic
def submit(actor: Actor, agreement_id, *, expected_version: int | None,
           counterparty_confirmed: bool = False) -> Agreement:
    agr = _lock(agreement_id)
    agr.assert_editable()
    _require_author(actor, agr, "Отправить")
    _require_status(agr, EDITABLE, "отправить")
    check_version(agr, expected_version)
    _check_required(agr)
    counterparties.assert_usable(agr.counterparty_id)       # BR-030, E-CTR-01
    if counterparties.needs_confirmation(agr.counterparty_id) and not counterparty_confirmed:
        raise DomainError(
            "E-CTR-05",
            f"Контрагент {counterparties.display_name(agr.counterparty)} ещё не проверен. "
            f"Подтвердите, что реквизиты сверены с документами, и отправьте снова.",
            fields=[{"field": "counterparty_confirmed", "message": "Нужно подтверждение"}])
    _recalc_vat(agr)
    if agr.with_vat and agr.vat_rate is None:
        raise DomainError(
            "E-VAT-01", "Не задана ставка НДС. Укажите ставку или обратитесь к "
                        "администратору справочников.",
            fields=[{"field": "vat_rate", "message": "Нет ставки"}])
    _check_duplicate(agr)
    _check_remaining(agr)
    _check_sum(agr)
    figures = _check_budget(agr)
    agr.counterparty_confirmed = agr.counterparty_confirmed or counterparty_confirmed
    agr.save()
    try:
        signoff.start_process(subject_type=SUBJECT, subject_id=str(agr.pk),
                              initiator_id=actor.user_id)
    except signoff.SignoffError as exc:
        raise _signoff_error(exc) from exc
    except IntegrityError as exc:
        # Параллельная отправка с тем же номером контрагента — BR-032 базой.
        raise DomainError("BR-032", "Договор с этими номером и датой у контрагента уже "
                                    "зарегистрирован. Обновите страницу.", status=409) from exc
    agr.refresh_from_db()
    agr.status_comment = ""
    _touch(agr, actor.user_id, "status_comment")
    changes = {"amount": str(agr.amount) if agr.amount is not None else None,
               "over_plan": str(over_plan(agr)), "available_before": str(figures["available"])}
    if counterparty_confirmed:
        changes["counterparty_confirmed"] = counterparties.display_name(agr.counterparty)
    audit.record(agr, "submitted", actor_id=actor.user_id, changes=changes)
    return agr


@transaction.atomic
def withdraw(actor: Actor, agreement_id, *, expected_version: int | None) -> Agreement:
    agr = _lock(agreement_id)
    _require_author(actor, agr, "Отозвать")
    _require_status(agr, (AgreementStatus.ON_REVIEW,), "отозвать")
    check_version(agr, expected_version)
    if _has_decisions(agr):
        raise DomainError(
            "E-STS-01", f"Нельзя отозвать договор {agr.number}: по нему уже есть решение. "
                        f"Попросите согласующего вернуть его на доработку.", status=409)
    try:
        signoff.cancel_process(process_id=_process(agr)["id"], actor_id=actor.user_id)
    except signoff.SignoffError as exc:
        raise _signoff_error(exc) from exc
    agr.refresh_from_db()
    _touch(agr, actor.user_id)
    audit.record(agr, "withdrawn", actor_id=actor.user_id)
    return agr


# ── действующий договор ─────────────────────────────────────────────────

def _comment(comment: str) -> str:
    comment = (comment or "").strip()
    if len(comment) < COMMENT_MIN:
        raise DomainError(
            "BR-060", "Опишите причину: комментарий не короче 10 символов.",
            fields=[{"field": "comment", "message": f"Минимум {COMMENT_MIN} символов"}])
    return comment


#: Счета до «Оплачено» (ТЗ §9.4: «Исполнен» — только без них).
UNPAID_INVOICE_STATUSES = (InvoiceStatus.DRAFT, InvoiceStatus.UNDER_REVIEW,
                           InvoiceStatus.RETURNED, InvoiceStatus.TO_PAY,
                           InvoiceStatus.PARTIALLY_PAID)


def _has_unpaid_invoices(agr: Agreement) -> bool:
    return Invoice.objects.filter(agreement=agr, status__in=UNPAID_INVOICE_STATUSES).exists()


@transaction.atomic
def fulfil(actor: Actor, agreement_id, *, expected_version: int | None) -> Agreement:
    """«Исполнен» — ФД, если нет счетов до «Оплачено» (ТЗ §9.4); новые счета
    запрещены, неосвоенные позиции возвращаются в план."""
    agr = _lock(agreement_id)
    if not actor.can("bpp.agreements.terminate", "edit"):
        raise _deny("Отмечает договор исполненным финансовый директор.")
    _require_status(agr, (AgreementStatus.ACTIVE,), "отметить исполненным")
    check_version(agr, expected_version)
    if _has_unpaid_invoices(agr):
        raise DomainError(
            "E-STS-01", f"Нельзя отметить договор {agr.number} исполненным: по нему есть "
                        f"неоплаченные счета.", status=409)
    agr.status = AgreementStatus.FULFILLED
    _touch(agr, actor.user_id, "status")
    audit.record(agr, "fulfilled", actor_id=actor.user_id)
    return agr


@transaction.atomic
def terminate(actor: Actor, agreement_id, *, expected_version: int | None,
              comment: str) -> Agreement:
    """«Расторгнуть» — ФД с комментарием (ТЗ §9.4): неоплаченные счета остаются,
    новые запрещены, резерв по неиспользованной части снимается (Q-D02)."""
    agr = _lock(agreement_id)
    if not actor.can("bpp.agreements.terminate", "edit"):
        raise _deny("Расторгает договор финансовый директор.")
    comment = _comment(comment)
    _require_status(agr, (AgreementStatus.ACTIVE,), "расторгнуть")
    check_version(agr, expected_version)
    agr.status, agr.status_comment = AgreementStatus.TERMINATED, comment
    _touch(agr, actor.user_id, "status", "status_comment")
    audit.record(agr, "terminated", actor_id=actor.user_id, comment=comment)
    return agr


@transaction.atomic
def create_supplement(actor: Actor, parent_id) -> Agreement:
    """Допсоглашение к действующему договору (D-18): те же реквизиты, сумма —
    прирост (0 — без изменения суммы), позиций нет, свой маршрут."""
    if not actor.can("bpp.agreements", "create"):
        raise _deny("Допсоглашения оформляют снабженцы и руководители проектов.")
    parent = _lock(parent_id)
    if not can_view(actor, parent):
        raise DomainError("E-NOT-FOUND", "Договор не найден.", status=404)
    _require_status(parent, (AgreementStatus.ACTIVE,), "оформить допсоглашение к")
    if parent.parent_agreement_id is not None:
        raise DomainError("E-VAL-01", "Допсоглашение оформляется к договору, а не к "
                                      "другому допсоглашению.")
    agr = Agreement.objects.create(
        number=next_number("ДГ"), author_id=actor.user_id,
        initiator_role=parent.initiator_role, project_id=parent.project_id,
        article_id=parent.article_id, counterparty=parent.counterparty,
        agreement_type=parent.agreement_type, is_open=parent.is_open,
        amount=None if parent.is_open else Decimal("0.00"),
        currency_code=parent.currency_code, with_vat=parent.with_vat,
        vat_rate=parent.vat_rate, vat_source=parent.vat_source,
        name=f"Дополнительное соглашение к договору {parent.ext_number or parent.number}",
        ext_date=timezone.localdate(), parent_agreement=parent,
        created_by=actor.user_id, updated_by=actor.user_id)
    _recalc_vat(agr)
    agr.save()
    audit.record(agr, "created", actor_id=actor.user_id,
                 changes={"supplement_to": parent.number})
    audit.record(parent, "supplement_created", actor_id=actor.user_id,
                 changes={"supplement": agr.number})
    return agr


# ── колбэки согласования ────────────────────────────────────────────────

def scope_of(agreement_id) -> str:
    parent = (Agreement.objects.filter(pk=agreement_id)
              .values_list("parent_agreement_id", flat=True).first())
    return SUPPLEMENTARY if parent else ""


def on_started(agreement_id) -> None:
    Agreement.objects.filter(pk=agreement_id).update(status=AgreementStatus.ON_REVIEW)


def on_approved(agreement_id) -> None:
    """«Действует» (BR-035). Допсоглашение: родитель остаётся действующим
    документом, суммы складываются (``effective_amount``), срок действия
    продлевается. Удачный документ контрагента (метка «Проверенный»)."""
    agr = Agreement.objects.select_related("parent_agreement").get(pk=agreement_id)
    Agreement.objects.filter(pk=agreement_id).update(status=AgreementStatus.ACTIVE,
                                                    rework_comment="")
    parent = agr.parent_agreement
    if parent is not None and agr.valid_to and (parent.valid_to is None
                                                or agr.valid_to > parent.valid_to):
        Agreement.objects.filter(pk=parent.pk).update(valid_to=agr.valid_to)
        audit.record_for(parent._meta.label_lower, str(parent.pk), "valid_to_extended",
                         actor_id=None, changes={"valid_to": agr.valid_to.isoformat(),
                                                 "supplement": agr.number})
    if agr.counterparty_id and parent is None:
        counterparties.record_success(agr.counterparty_id)


def on_rejected(agreement_id) -> None:
    Agreement.objects.filter(pk=agreement_id).update(status=AgreementStatus.REJECTED)


def _last_rework_comment(agreement_id) -> str:
    process = signoff.get_process_for(SUBJECT, str(agreement_id))
    comments = [task.get("comment") or "" for stage in (process or {}).get("stages", [])
                for task in stage["tasks"] if task["state"] == "rework"]
    return comments[-1] if comments else ""


def on_rework(agreement_id) -> None:
    Agreement.objects.filter(pk=agreement_id).update(
        status=AgreementStatus.REWORK, rework_comment=_last_rework_comment(agreement_id))


def on_cancelled(agreement_id) -> None:
    Agreement.objects.filter(pk=agreement_id).update(status=AgreementStatus.DRAFT)


def facts(agreement_id) -> dict:
    """Факты для ветвления маршрута: сумма, прирост допсоглашения
    (``amount_delta``, D-18), тип, открытый, группа статьи."""
    agr = Agreement.objects.filter(pk=agreement_id).first()
    if agr is None:
        return {}
    brief = refdata.article_brief([str(agr.article_id)]).get(str(agr.article_id))
    groups = {g["id"]: g["code"] for g in refdata.article_groups()}
    supplement = agr.parent_agreement_id is not None
    return {
        "amount": agr.amount or Decimal("0"),
        "amount_delta": (agr.amount or Decimal("0")) if supplement else Decimal("0"),
        "is_supplement": supplement,
        "agreement_type": agr.agreement_type,
        "is_open": agr.is_open,
        "currency": agr.currency_code,
        "article_group": groups.get(brief["group_id"], "") if brief else "",
    }
