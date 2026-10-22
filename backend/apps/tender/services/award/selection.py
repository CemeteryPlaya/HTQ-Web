"""Выбор поставщиков (T5.2; спека этапа 5, §3 T5.2; ТЗ TND-022; S5-05…S5-07).

Закупщик (автор тендера) выбирает поставщика по каждой позиции и строки
доставки/СМР — после вскрытия, в статусах «Вскрыт» и «Возвращён на
доработку». Выбор сохраняется целиком (``PUT``): прежний заменяется.

- У позиции — один поставщик (S5-05); количество — не больше предложенного.
- Доставка и СМР — только у поставщика, выигравшего хотя бы одну позицию
  (S5-06): чужую доставку к чужому товару не возят. Доставка или СМР «в цене»
  у победителя выбираются сами (сумма 0) — их часть закроется при передаче.
- Строка не самая дешёвая (цена за единицу в KZT у позиции, сумма — у
  доставки и СМР) — нужны **оба** комментария (S5-07, ответ ФД 20.10):
  общий к выбору и свой у каждой такой строки, не короче 10 символов;
  иначе 422 ``E-TND-12`` с перечнем строк.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django.db import transaction

from apps.tender.models import Award, PartKind, Tender, TenderStatus
from apps.tender.services.comparison import money, table
from apps.tender.services.comparison.opening import require_opened
from apps.tender.services.core import audit
from apps.tender.services.core.errors import check_version
from apps.tender.services.tenders import tenders
from apps.tender.services.tenders.ctx import Ctx, bad
from htqweb.errors import DomainError

EDITABLE = (TenderStatus.OPENED, TenderStatus.REWORK)
COMMENT_MIN = 10
ZERO = Decimal("0")


def _qty(value, offered: Decimal, field: str) -> Decimal:
    if value in (None, ""):
        return offered
    try:
        qty = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise bad(field, "количество — число") from None
    if qty <= 0 or qty > offered:
        raise bad(field, f"количество — больше нуля и не больше предложенного ({offered})")
    return qty


def plans_by_part(tender: Tender) -> dict[str, dict]:
    """План каждой части заявки в KZT: позиции — плановая цена × запрошенное
    количество; доставка и СМР — плановые суммы заявки."""
    req = tender.request
    out = {}
    for part in req.parts.filter(excluded_at__isnull=True):
        if part.kind == PartKind.GOODS:
            plan = sum((money.money(i.plan_price * i.qty) for i in req.items.filter(part=part)),
                       ZERO)
        elif part.kind == PartKind.DELIVERY:
            plan = req.delivery_plan_amount or ZERO
        else:
            plan = req.works_plan_amount or ZERO
        out[str(part.pk)] = {"part": part, "plan": plan}
    return out


@transaction.atomic
def save(ctx: Ctx, tender_id, data: dict) -> dict:
    tender = tenders.get_own(ctx, tender_id, "Выбирать поставщиков в")
    if tender.status not in EDITABLE:
        raise tenders.state_error("выбирать поставщиков в", tender)
    require_opened(tender)
    check_version(tender, data.get("version"))

    offers = table.offers_of(tender)
    rates = table.rates_for(tender, offers)
    rate = {o.pk: (rates.get(o.currency_code).rate if rates.get(o.currency_code) else None)
            for o in offers}
    by_line = {str(line.pk): (o, line) for o in offers for line in o.lines.all()
               if line.participates and line.price is not None}
    by_extra = {str(e.pk): (o, e) for o in offers for e in o.extras.all()}
    parts = {p["part"].kind if p["part"].kind != PartKind.GOODS else None: p["part"]
             for p in plans_by_part(tender).values()}
    plans = table.requested_extras(tender)
    plan_of_kind = {kind: plan or ZERO for kind, plan in plans}

    unit_min: dict = {}
    for o, line in by_line.values():
        unit = money.to_kzt(line.price, rate[o.pk])
        if unit is not None and (line.item_id not in unit_min or unit < unit_min[line.item_id]):
            unit_min[line.item_id] = unit
    extra_min: dict = {}
    for o, e in by_extra.values():
        in_kzt = money.to_kzt(table.extra_amount(o, e), rate[o.pk])
        if in_kzt is not None and (e.kind not in extra_min or in_kzt < extra_min[e.kind]):
            extra_min[e.kind] = in_kzt

    rows, taken, missing = [], {}, []
    for i, row in enumerate(data.get("lines") or []):
        found = by_line.get(str(row.get("line_id")))
        if found is None:
            raise bad(f"lines[{i}].line_id", "строка предложения не найдена в этом тендере")
        o, line = found
        if line.item_id in taken:
            raise bad(f"lines[{i}].line_id",
                      "позиция уже выбрана у другого поставщика — у позиции один поставщик")
        qty = _qty(row.get("qty"), line.qty, f"lines[{i}].qty")
        taken[line.item_id] = o.invitation_id
        amount = money.gross(line.price * qty, with_vat=o.with_vat, vat_rate=o.vat_rate)
        unit = money.to_kzt(line.price, rate[o.pk])
        cheapest = unit is not None and unit <= unit_min.get(line.item_id, unit)
        comment = (row.get("comment") or "").strip()
        if not cheapest and len(comment) < COMMENT_MIN:
            missing.append((f"lines[{i}].comment", {"line_id": str(line.pk),
                                                    "item_id": str(line.item_id)}))
        rows.append(Award(tender=tender, offer=o, line=line, part_id=line.item.part_id,
                          qty=qty, amount=amount, amount_kzt=money.to_kzt(amount, rate[o.pk]),
                          plan_amount_kzt=money.money(line.item.plan_price * qty),
                          is_cheapest=cheapest, comment=comment,
                          created_by=ctx.user_id, updated_by=ctx.user_id))
    winners = set(taken.values())

    chosen = set()
    for j, row in enumerate(data.get("extras") or []):
        key = str(row.get("extra_id"))
        found = by_extra.get(key)
        if found is None or key in chosen:
            raise bad(f"extras[{j}].extra_id", "строка доставки или СМР не найдена в этом тендере")
        o, e = found
        if o.invitation_id not in winners:
            raise bad(f"extras[{j}].extra_id", "доставку и СМР выбирают у поставщика, который "
                                               "выиграл хотя бы одну позицию")
        chosen.add(key)
        comment = (row.get("comment") or "").strip()
        rows.append(_extra_award(ctx, tender, o, e, parts, plan_of_kind, rate, extra_min,
                                 comment, missing, f"extras[{j}].comment"))
    for o in offers:                       # «в цене» у победителя — сам
        if o.invitation_id not in winners:
            continue
        for e in o.extras.all():
            if e.included_in_price and str(e.pk) not in chosen:
                rows.append(_extra_award(ctx, tender, o, e, parts, plan_of_kind, rate,
                                         extra_min, "", missing, None))

    general = (data.get("comment") or "").strip()
    not_cheapest = [r for r in rows if not r.is_cheapest]
    fields = []
    if not_cheapest and len(general) < COMMENT_MIN:
        fields.append({"field": "comment", "message": "объясните выбор — не короче 10 символов"})
    fields += [{"field": f, "message": "не самый дешёвый вариант — объясните выбор строки"}
               for f, _row in missing if f]
    if fields:
        raise DomainError(
            "E-TND-12", "Выбран не самый дешёвый вариант. Объясните выбор: общий комментарий "
                        "и комментарий к каждой такой строке — не короче 10 символов.",
            fields=fields, details={"rows": [row for f, row in missing if f]})

    Award.objects.filter(tender=tender).delete()
    Award.objects.bulk_create(rows)
    tender.award_comment = general
    tenders._touch(tender, ctx.user_id)
    audit.record(tender, "award_saved", actor_id=ctx.user_id, comment=general,
                 changes={"lines": len([r for r in rows if r.line_id]),
                          "extras": len([r for r in rows if r.extra_id]),
                          "not_cheapest": len(not_cheapest)})
    return view_of(ctx, tender)


def _extra_award(ctx, tender, offer, extra, parts, plan_of_kind, rate, extra_min, comment,
                 missing, field) -> Award:
    part = parts.get(extra.kind)
    if part is None:
        raise bad(field or "extras", f"в заявке нет части «{extra.get_kind_display()}»")
    amount = table.extra_amount(offer, extra)
    in_kzt = money.to_kzt(amount, rate[offer.pk])
    cheapest = in_kzt is not None and in_kzt <= extra_min.get(extra.kind, in_kzt)
    if not cheapest and len(comment) < COMMENT_MIN:
        missing.append((field, {"extra_id": str(extra.pk), "kind": extra.kind}))
    return Award(tender=tender, offer=offer, extra=extra, part_id=part.pk, qty=Decimal("1"),
                 amount=amount, amount_kzt=in_kzt,
                 plan_amount_kzt=plan_of_kind.get(extra.kind, ZERO), is_cheapest=cheapest,
                 comment=comment, created_by=ctx.user_id, updated_by=ctx.user_id)


def view(ctx: Ctx, tender_id) -> dict:
    tender = tenders.get_visible(ctx, tender_id)
    require_opened(tender)
    return view_of(ctx, tender)


def _s(value) -> str | None:
    return None if value is None else str(value)


def view_of(ctx: Ctx, tender: Tender) -> dict:
    awards = list(tender.awards.select_related("offer__invitation", "line__item", "extra")
                  .order_by("line__item__line_no", "extra__kind"))
    lines, extras, suppliers, parts = [], [], {}, {}
    for a in awards:
        inv = a.offer.invitation
        base = {"award_id": str(a.pk), "invitation_id": str(inv.pk), "supplier": inv.name,
                "part_id": str(a.part_id), "qty": str(a.qty), "amount": str(a.amount),
                "currency_code": a.offer.currency_code, "amount_kzt": _s(a.amount_kzt),
                "plan_amount_kzt": str(a.plan_amount_kzt), "is_cheapest": a.is_cheapest,
                "comment": a.comment}
        if a.line_id:
            lines.append({**base, "line_id": str(a.line_id), "item_id": str(a.line.item_id),
                          "line_no": a.line.item.line_no, "name": a.line.item.name,
                          "price": str(a.line.price), "is_analog": a.line.is_analog})
        else:
            extras.append({**base, "extra_id": str(a.extra_id), "kind": a.extra.kind,
                           "included_in_price": a.extra.included_in_price})
        s = suppliers.setdefault(str(inv.pk), {
            "invitation_id": str(inv.pk), "name": inv.name,
            "currency_code": a.offer.currency_code, "amount": ZERO, "amount_kzt": ZERO,
            "complete_rate": True})
        s["amount"] += a.amount
        if a.amount_kzt is None:
            s["complete_rate"] = False
        else:
            s["amount_kzt"] += a.amount_kzt
        p = parts.setdefault(str(a.part_id), ZERO)
        parts[str(a.part_id)] = p + (a.amount_kzt or ZERO)
    plans = plans_by_part(tender)
    return {
        "tender_id": str(tender.pk), "version": tender.version, "status": tender.status,
        "comment": tender.award_comment, "status_comment": tender.status_comment,
        "lines": lines, "extras": extras,
        "suppliers": [{**s, "amount": str(s["amount"]),
                       "amount_kzt": str(s["amount_kzt"]) if s["complete_rate"] else None}
                      for s in suppliers.values()],
        "parts": [{"part_id": key, "kind": row["part"].kind,
                   "article_id": str(row["part"].article_id), "plan_kzt": str(row["plan"]),
                   "amount_kzt": str(parts.get(key, ZERO)),
                   "over_plan_kzt": str(max(parts.get(key, ZERO) - row["plan"], ZERO))}
                  for key, row in plans.items()],
        "allowed_actions": tenders.allowed_actions(ctx, tender),
    }
