"""Чтение альтернативных предложений: лента L-09 «Закупки для альтернатив»,
сравнение предложений, карточка АП, «Мои альтернативы» (ТЗ §12.2–12.4, F-07;
план этапа 5 A, задача 4).

**Видимость АП** — одна проверка ``can_view`` на карточку, «Историю
изменений» (``file_owner.HISTORY_CHECKS``) и КП в ``apps.files``
(``file_owner._can_view``):

- автор видит свою АП всегда, черновик — только он;
- ФД, ТД, ОД, ГД (``bpp.alternatives`` view без права создавать счета — как
  ``invoices.sees_all``) — все поданные;
- автор исходного документа — поданные к своему документу (у ПМ это
  «V (свои документы)» матрицы, у СН — АП к его документу);
- остальным (в том числе другому СН) чужая АП — 404.

**Лента** (ТЗ §12.2): счета без договора «На рассмотрении ФД» (ещё без решения) и
договоры «На согласовании» — те, к которым АП вообще подаётся (открытый
договор и допсоглашение не входят, D-S5-5), в том числе свои. СН и
руководство видят все (в пределах видимых проектов), ПМ — только свои
документы; без ``bpp.alternatives`` view — 403. Счёт и договор сводятся в
одну выборку ``UNION ALL`` с общими колонками, «альтернатив подано» (АП
«Подано» и «Выбрано» — как в лимите документа, D-S5-2), «отправлен» (последняя
запись журнала ``submitted``) и «моя альтернатива» — подзапросами, без N+1;
наименования позиций, контрагенты, авторы, проекты и статьи страницы —
пакетно, по запросу на вид.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from django.db.models import (
    CharField,
    Count,
    DateTimeField,
    Exists,
    F,
    IntegerField,
    OuterRef,
    Q,
    Subquery,
    UUIDField,
    Value,
)
from django.db.models.functions import Cast, Coalesce

from apps.bpp.models import (
    Agreement,
    AgreementItem,
    AgreementStatus,
    AlternativeOffer,
    AlternativeOfferLine,
    AuditLog,
    Invoice,
    InvoiceBasis,
    InvoiceLine,
    InvoiceStatus,
    OfferStatus,
)
from apps.bpp.models.alternatives import OfferSource
from apps.bpp.services.actor import Actor
from apps.bpp.services.alternatives import calc as offer_calc
from apps.bpp.services.alternatives import offers
from apps.bpp.services.core import files as core_files
from apps.bpp.services.counterparties import lookup as counterparties
from apps.project import interface as projects
from apps.refdata import interface as refdata
from apps.users import interface as users
from htqweb.errors import DomainError

__all__ = [
    "FeedFilters", "can_view", "card", "comparison", "deviation_pct", "feed", "get_visible",
    "my_offers", "sees_all",
]

NODE = offers.NODE
INVOICE, AGREEMENT = offers.SOURCE_INVOICE, offers.SOURCE_AGREEMENT
KINDS = (INVOICE, AGREEMENT)
KIND_LABELS = dict(OfferSource.choices)
#: «Альтернатив подано» — как лимит документа (D-S5-2): «Отозвано»,
#: «Аннулировано» и черновики не считаются.
FILED = (OfferStatus.SUBMITTED.value, OfferStatus.SELECTED.value)
PAGE_SIZES = (25, 50, 100)
PREVIEW_POSITIONS = 3
_PCT = Decimal("0.01")

#: Позиции исходного документа: модель строки и её ключ на документ.
_LINES = {INVOICE: (InvoiceLine, "invoice_id"), AGREEMENT: (AgreementItem, "agreement_id")}
#: Общие колонки ленты — одинаковый порядок в обеих частях ``UNION ALL``.
_FEED_COLUMNS = ("id", "source_type", "number", "author_id", "project_id", "article_id",
                 "counterparty_id", "amount", "currency_code", "alt_limit", "created_at",
                 "sent_at", "offers_count", "my_offer_id")


def _text(value):
    return None if value is None else str(value)


def _names(ids) -> dict[int, str]:
    ids = [uid for uid in set(ids) if uid]
    return {row["id"]: row["full_name"] for row in users.get_users_brief(ids)} if ids else {}


# ── права и видимость ───────────────────────────────────────────────────

def _is_superuser(actor: Actor) -> bool:
    return bool(getattr(actor.request.token, "is_superuser", False))


def sees_all(actor: Actor) -> bool:
    """ФД, ТД, ОД, ГД: ``bpp.alternatives`` view без права создавать счета
    (у СН и ПМ оно есть) — то же различие, что ``invoices.sees_all``."""
    return _is_superuser(actor) or (actor.can(NODE, "view")
                                    and not actor.can("bpp.invoices", "create"))


def _proposes(actor: Actor) -> bool:
    """Подаёт АП (СН по матрице): видит в ленте все документы, а не свои."""
    return actor.can(NODE, "create")


def _require_viewer(actor: Actor) -> None:
    if not (_is_superuser(actor) or actor.can(NODE, "view")):
        raise offers._deny("Раздел «Закупки для альтернатив» вам недоступен.")


def _source_author(offer: AlternativeOffer) -> int | None:
    model = offers._MODELS.get(offer.source_type)
    if model is None:
        return None
    return model.objects.filter(pk=offer.source_id).values_list("author_id", flat=True).first()


def can_view(actor: Actor, offer: AlternativeOffer) -> bool:
    """Автор; черновик — только он; поданную — ФД, ТД, ОД, ГД и автор
    исходного документа (ПМ — «свои документы»). Журнал и КП — по ней же."""
    if offer.author_id == actor.user_id:
        return True
    if offer.status == OfferStatus.DRAFT:
        return False
    if sees_all(actor):
        return True
    return _source_author(offer) == actor.user_id


def get_visible(actor: Actor, offer_id) -> AlternativeOffer:
    key = offers._key(offer_id)
    offer = AlternativeOffer.objects.filter(pk=key).first() if key else None
    if offer is None or not can_view(actor, offer):
        raise offers._not_found()
    return offer


def _sees_source(actor: Actor, source) -> bool:
    """Сравнение по документу: руководство, автор документа, СН в пределах
    видимых проектов; ПМ — только свои документы."""
    if sees_all(actor) or source.author_id == actor.user_id:
        return True
    return _proposes(actor) and actor.sees_project(source.project_id)


def deviation_pct(price, source_price) -> Decimal | None:
    """Отклонение цены АП от исходной, %: (цена − исходная) / исходная × 100,
    0,01 ``ROUND_HALF_UP``; плюс — дороже. Нет цены — ``None``."""
    if price is None or source_price is None or not Decimal(source_price):
        return None
    base = Decimal(source_price)
    return ((Decimal(price) - base) * 100 / base).quantize(_PCT, rounding=ROUND_HALF_UP)


# ── лента L-09 ──────────────────────────────────────────────────────────

@dataclass
class FeedFilters:
    kind: str | None = None
    author_id: int | None = None
    project_ids: list[str] = field(default_factory=list)
    article_ids: list[str] = field(default_factory=list)
    counterparty_id: str | None = None
    q: str | None = None
    amount_from: Decimal | None = None
    amount_to: Decimal | None = None
    sent_from: date | None = None
    sent_to: date | None = None
    without_offers: bool = False
    mine: bool | None = None
    source: tuple[str, str] | None = None


def _open_sources(kind: str):
    """Документы в окне подачи (BR-090), к которым АП подаётся вообще, —
    выборка обязана совпадать с ``offers.window_open`` и ``offers._check_kind``:
    решение ФД уводит счёт из «На рассмотрении ФД», поэтому решённый счёт
    сюда не попадает, а ``fd_decided_at`` (остаётся после возврата и
    повторной отправки) не смотрим — как и окно подачи."""
    if kind == INVOICE:
        return Invoice.objects.filter(basis=InvoiceBasis.NO_CONTRACT,
                                      status=InvoiceStatus.UNDER_REVIEW)
    return Agreement.objects.filter(status=AgreementStatus.ON_REVIEW, is_open=False,
                                    parent_agreement__isnull=True)


def _annotate(kind: str, rows, actor: Actor):
    audit_type = offers._MODELS[kind]._meta.label_lower
    sent = (AuditLog.objects
            .filter(object_type=audit_type, action="submitted",
                    object_id=Cast(OuterRef("pk"), output_field=CharField()))
            .order_by("-created_at").values("created_at")[:1])
    filed = (AlternativeOffer.objects
             .filter(source_type=kind, source_id=OuterRef("pk"), status__in=FILED)
             .order_by().values("source_id").annotate(n=Count("pk")).values("n"))
    mine = (AlternativeOffer.objects
            .filter(source_type=kind, source_id=OuterRef("pk"), author_id=actor.user_id)
            .exclude(status=OfferStatus.ANNULLED).order_by("-created_at").values("pk")[:1])
    return rows.annotate(
        source_type=Value(kind, output_field=CharField()),
        sent_at=Subquery(sent, output_field=DateTimeField()),
        offers_count=Coalesce(Subquery(filed, output_field=IntegerField()), Value(0)),
        my_offer_id=Subquery(mine, output_field=UUIDField()),
    )


def _feed_part(kind: str, actor: Actor, filters: FeedFilters):
    if filters.kind and filters.kind != kind:
        return None
    if filters.source and filters.source[0] != kind:
        return None
    rows = _open_sources(kind)
    if not (sees_all(actor) or _proposes(actor)):
        rows = rows.filter(author_id=actor.user_id)          # ПМ — свои документы
    elif not actor.sees_all_projects:
        rows = rows.filter(project_id__in=list(actor.member_project_ids))
    if filters.source:
        rows = rows.filter(pk=filters.source[1])
    if filters.author_id is not None:
        rows = rows.filter(author_id=filters.author_id)
    if filters.project_ids:
        rows = rows.filter(project_id__in=filters.project_ids)
    if filters.article_ids:
        rows = rows.filter(article_id__in=filters.article_ids)
    if filters.counterparty_id:
        rows = rows.filter(counterparty_id=filters.counterparty_id)
    if filters.q:
        model, key = _LINES[kind]
        rows = rows.filter(Exists(model.objects.filter(
            **{key: OuterRef("pk")}, request_item__name__icontains=filters.q)))
    if filters.amount_from is not None:
        rows = rows.filter(amount__gte=filters.amount_from)
    if filters.amount_to is not None:
        rows = rows.filter(amount__lte=filters.amount_to)
    rows = _annotate(kind, rows, actor)
    if filters.sent_from:
        rows = rows.filter(sent_at__date__gte=filters.sent_from)
    if filters.sent_to:
        rows = rows.filter(sent_at__date__lte=filters.sent_to)
    if filters.without_offers:
        rows = rows.filter(offers_count=0)
    if filters.mine is not None:
        rows = rows.filter(my_offer_id__isnull=not filters.mine)
    return rows.order_by().values(*_FEED_COLUMNS)


def _positions(kind: str, ids: list) -> dict[str, list[str]]:
    if not ids:
        return {}
    model, key = _LINES[kind]
    out: dict[str, list[str]] = {}
    for owner, name in (model.objects.filter(**{f"{key}__in": ids})
                        .order_by(key, "created_at").values_list(key, "request_item__name")):
        out.setdefault(str(owner), []).append(name)
    return out


def _feed_rows(rows: list[dict]) -> list[dict]:
    names_by_doc = {
        **_positions(INVOICE, [r["id"] for r in rows if r["source_type"] == INVOICE]),
        **_positions(AGREEMENT, [r["id"] for r in rows if r["source_type"] == AGREEMENT]),
    }
    cps = counterparties.brief([r["counterparty_id"] for r in rows if r["counterparty_id"]])
    my_ids = [r["my_offer_id"] for r in rows if r["my_offer_id"]]
    mine = {str(o["id"]): o for o in
            AlternativeOffer.objects.filter(pk__in=my_ids).values("id", "number", "status")}
    authors = _names([r["author_id"] for r in rows])
    project_map = projects.project_brief(list({str(r["project_id"]) for r in rows}))
    article_map = refdata.article_brief(list({str(r["article_id"]) for r in rows}))
    labels = dict(OfferStatus.choices)
    out = []
    for r in rows:
        key, kind = str(r["id"]), r["source_type"]
        position_names = names_by_doc.get(key, [])
        cp = cps.get(str(r["counterparty_id"])) if r["counterparty_id"] else None
        project = project_map.get(str(r["project_id"]), {})
        article = article_map.get(str(r["article_id"]), {})
        my = mine.get(str(r["my_offer_id"])) if r["my_offer_id"] else None
        out.append({
            "source_type": kind, "source_id": key, "number": r["number"],
            "kind_label": KIND_LABELS.get(kind, kind), "url": f"{offers._URLS[kind]}{key}",
            "author_id": r["author_id"], "author_name": authors.get(r["author_id"]),
            "project": {"id": str(r["project_id"]), "code": project.get("code"),
                        "name": project.get("name")},
            "article": {"id": str(r["article_id"]), "code": article.get("code"),
                        "name": article.get("name")},
            "counterparty": None if cp is None else {
                "id": cp["id"], "name": cp["short_name"] or cp["name"],
                "reg_number": cp["reg_number"]},
            "positions": {"names": position_names[:PREVIEW_POSITIONS],
                          "more": max(len(position_names) - PREVIEW_POSITIONS, 0),
                          "count": len(position_names)},
            "amount": _text(r["amount"]), "currency_code": r["currency_code"],
            "sent_at": r["sent_at"], "offers_count": r["offers_count"],
            "alt_limit": r["alt_limit"],
            "my_offer": None if my is None else {
                "id": str(my["id"]), "number": my["number"], "status": my["status"],
                "status_label": labels.get(my["status"], my["status"])},
        })
    return out


def feed(actor: Actor, filters: FeedFilters | None = None, *, page: int = 1,
         page_size: int = 50) -> dict:
    """Лента L-09 ``{items, total, page, page_size}``: новые отправки сверху."""
    _require_viewer(actor)
    filters = filters or FeedFilters()
    page_size = page_size if page_size in PAGE_SIZES else 50
    page = max(page, 1)
    parts = [part for part in (_feed_part(kind, actor, filters) for kind in KINDS)
             if part is not None]
    if not parts:
        return {"items": [], "total": 0, "page": page, "page_size": page_size}
    rows = parts[0] if len(parts) == 1 else parts[0].union(*parts[1:], all=True)
    total = rows.count()
    ordered = rows.order_by(F("sent_at").desc(nulls_last=True), F("created_at").desc(),
                            F("id").desc())
    chunk = list(ordered[(page - 1) * page_size: page * page_size])
    return {"items": _feed_rows(chunk), "total": total, "page": page, "page_size": page_size}


# ── сравнение (ТЗ §12.4 п.2) ────────────────────────────────────────────

def _source_positions(source) -> list[dict]:
    """Позиции исходного документа с наименованием; сумма позиции договора без
    своей суммы — сумма позиции заявки (как ``offers._source_lines``)."""
    if isinstance(source, Invoice):
        rows = source.lines.select_related("request_item").order_by("created_at")
    else:
        rows = source.items.select_related("request_item").order_by("created_at")
    out = []
    for row in rows:
        amount = row.amount if row.amount is not None else row.request_item.amount
        out.append({"id": str(row.pk), "item": row.request_item.sys_number,
                    "name": row.request_item.name, "uom_id": str(row.request_item.uom_id),
                    "need_date": row.request_item.need_date, "qty": row.qty,
                    "amount": amount,
                    "source_price": offer_calc.source_price(amount, row.qty)})
    return out


def _cp_view(brief: dict | None, countries: dict) -> dict | None:
    if brief is None:
        return None
    country = countries.get(brief["country_code"]) or {}
    return {**brief, "country_name": country.get("name")}


def _my_offer_id(actor: Actor, kind: str, source_id) -> str | None:
    key = (AlternativeOffer.objects
           .filter(source_type=kind, source_id=source_id, author_id=actor.user_id)
           .exclude(status=OfferStatus.ANNULLED).order_by("-created_at")
           .values_list("pk", flat=True).first())
    return _text(key)


def _propose_check(actor: Actor, source) -> str | None:
    """Почему кнопка «Предложить альтернативу» недоступна (BR-090, лимиты
    документа и автора, D-S5-2); ``None`` — доступна. Тексты — те же, что
    вернёт ``offers.create``."""
    if not _proposes(actor) or not actor.sees_project(source.project_id):
        return "Альтернативные предложения подают снабженцы."
    try:
        offers._check_kind(source)
        if not offers.window_open(source):
            raise offers._window_closed()
        offers._check_document_limit(source)
        offers._check_author_limit(source, actor.user_id, offers._author_role(actor))
    except DomainError as exc:
        return exc.message
    return None


def _offer_column(offer: AlternativeOffer, cps: dict, countries: dict,
                  authors: dict) -> dict:
    saving = offer.saving_amount
    return {
        "kind": "offer", "id": str(offer.pk), "number": offer.number,
        "version": offer.version, "status": offer.status,
        "status_label": offer.get_status_display(),
        "counterparty": _cp_view(cps.get(str(offer.counterparty_id)), countries)
        if offer.counterparty_id else None,
        "currency_code": offer.currency_code, "amount": _text(offer.amount),
        "amount_kzt": _text(offer.amount_kzt), "with_vat": offer.with_vat,
        "vat_rate": _text(offer.vat_rate), "vat_amount": _text(offer.vat_amount),
        "source_amount_kzt": _text(offer.source_amount_kzt),
        "saving": {"amount": _text(saving), "pct": _text(offer.saving_pct),
                   "more_expensive": saving is not None and saving < 0},
        "delivery_date": offer.delivery_date, "payment_terms": offer.payment_terms,
        "payment_terms_note": offer.payment_terms_note,
        "justification": offer.justification,
        "files": core_files.list_files(offer),
        "author": {"id": offer.author_id, "name": authors.get(offer.author_id),
                   "role": offer.author_role},
        "own_document": offer.own_document, "submitted_at": offer.submitted_at,
        "decided_at": offer.decided_at, "decision_comment": offer.decision_comment,
        "url": f"/bpp/alternatives/{offer.pk}",
    }


def comparison(actor: Actor, source_type: str, source_id) -> dict:
    """Исходный документ и видимые АП в колонках (чужие черновики — нет),
    позиции — «исходная цена / цена АП» по каждой позиции."""
    _require_viewer(actor)
    source = offers.source_of(source_type, source_id)
    if not _sees_source(actor, source):
        raise offers._not_found("Документ не найден.")
    kind = offers.source_kind(source)
    rows = (AlternativeOffer.objects.filter(source_type=kind, source_id=source.pk)
            .select_related("counterparty").order_by("created_at"))
    if sees_all(actor) or source.author_id == actor.user_id:
        rows = rows.filter(Q(author_id=actor.user_id) | ~Q(status=OfferStatus.DRAFT))
    else:
        rows = rows.filter(author_id=actor.user_id)
    offer_list = list(rows)

    cp_ids = [o.counterparty_id for o in offer_list if o.counterparty_id]
    if source.counterparty_id:
        cp_ids.append(source.counterparty_id)
    cps = counterparties.brief(cp_ids)
    countries = refdata.country_brief(list({b["country_code"] for b in cps.values()}))
    authors = _names([source.author_id, *[o.author_id for o in offer_list]])
    positions = _source_positions(source)
    uoms = refdata.uom_brief(list({p["uom_id"] for p in positions}))

    prices: dict[str, dict] = {}
    for line in (AlternativeOfferLine.objects.filter(offer_id__in=[o.pk for o in offer_list])
                 .values("offer_id", "source_line_id", "source_price", "price", "amount")):
        prices.setdefault(str(line["source_line_id"]), {})[str(line["offer_id"])] = {
            "price": _text(line["price"]), "amount": _text(line["amount"]),
            "deviation_pct": _text(deviation_pct(line["price"], line["source_price"])),
        }

    if isinstance(source, Invoice):
        amount_kzt = source.amount_kzt
    else:
        amount_kzt = (offers._source_part_kzt(source, source.amount)
                      if source.amount is not None else None)
    need_dates = [p["need_date"] for p in positions if p["need_date"]]
    source_column = {
        "kind": "source", "source_type": kind, "id": str(source.pk), "number": source.number,
        "status": source.status, "status_label": source.get_status_display(),
        "url": f"{offers._URLS[kind]}{source.pk}",
        "counterparty": _cp_view(cps.get(str(source.counterparty_id)), countries)
        if source.counterparty_id else None,
        "currency_code": source.currency_code, "amount": _text(source.amount),
        "amount_kzt": _text(amount_kzt), "with_vat": source.with_vat,
        "vat_rate": _text(source.vat_rate), "vat_amount": _text(source.vat_amount),
        # «Срок» исходного документа — самая ранняя дата потребности его позиций.
        "delivery_date": min(need_dates) if need_dates else None,
        "payment_terms": None,
        "author": {"id": source.author_id, "name": authors.get(source.author_id)},
    }
    blocked = _propose_check(actor, source)
    return {
        "source": source_column,
        "offers": [_offer_column(o, cps, countries, authors) for o in offer_list],
        "positions": [{
            "source_line_id": p["id"], "item": p["item"], "name": p["name"],
            "uom": uoms.get(p["uom_id"], {}).get("short_name"), "qty": _text(p["qty"]),
            "source_price": _text(p["source_price"]), "source_amount": _text(p["amount"]),
            "offers": prices.get(p["id"], {}),
        } for p in positions],
        "limit": source.alt_limit,
        "submitted_count": offers._decided_count(source),
        "window_open": offers.window_open(source),
        "can_propose": blocked is None,
        "propose_blocked_reason": blocked,
        "my_offer_id": _my_offer_id(actor, kind, source.pk),
    }


# ── карточка F-07 ───────────────────────────────────────────────────────

def card(actor: Actor, offer: AlternativeOffer) -> dict:
    """Поля F-07 (``offers.serialize``) плюс исходный документ (контрагент,
    сумма, статус), проект, статья, автор и отклонение цены по строкам."""
    data = offers.serialize(actor, offer)
    source = offers._MODELS[offer.source_type].objects.filter(pk=offer.source_id).first()
    project = projects.project_brief([str(offer.project_id)]).get(str(offer.project_id)) \
        if offer.project_id else None
    article = refdata.article_brief([str(offer.article_id)]).get(str(offer.article_id)) \
        if offer.article_id else None
    cp_ids = [source.counterparty_id] if source is not None and source.counterparty_id else []
    cps = counterparties.brief(cp_ids)
    authors = _names([offer.author_id, source.author_id if source is not None else None])
    if source is not None:
        data["source"].update({
            "status": source.status, "status_label": source.get_status_display(),
            "amount": _text(source.amount),
            "counterparty": cps.get(str(source.counterparty_id))
            if source.counterparty_id else None,
            "author_id": source.author_id, "author_name": authors.get(source.author_id),
        })
    for line in data["lines"]:
        line["deviation_pct"] = _text(deviation_pct(line["price"], line["source_price"]))
    data.update({
        "author_name": authors.get(offer.author_id),
        "project": None if project is None else {
            "id": str(offer.project_id), "code": project.get("code"),
            "name": project.get("name")},
        "article": None if article is None else {
            "id": str(offer.article_id), "code": article.get("code"),
            "name": article.get("name")},
        "more_expensive": offer.saving_amount is not None and offer.saving_amount < 0,
    })
    return data


# ── «Мои альтернативы» ──────────────────────────────────────────────────

def my_offers(actor: Actor, *, statuses: list[str] | None = None, page: int = 1,
              page_size: int = 50) -> dict:
    """АП автора (любые статусы или ``statuses``), новые сверху."""
    _require_viewer(actor)
    page_size = page_size if page_size in PAGE_SIZES else 50
    page = max(page, 1)
    rows = AlternativeOffer.objects.filter(author_id=actor.user_id)
    if statuses:
        rows = rows.filter(status__in=statuses)
    total = rows.count()
    chunk = list(rows.select_related("counterparty")
                 .order_by("-created_at")[(page - 1) * page_size: page * page_size])
    numbers: dict[str, str] = {}
    for kind in KINDS:
        ids = [o.source_id for o in chunk if o.source_type == kind]
        if ids:
            numbers.update({str(pk): number for pk, number in offers._MODELS[kind].objects
                            .filter(pk__in=ids).values_list("pk", "number")})
    items = [{
        "id": str(o.pk), "number": o.number, "version": o.version, "status": o.status,
        "status_label": o.get_status_display(),
        "source": {"type": o.source_type, "id": str(o.source_id),
                   "number": numbers.get(str(o.source_id)),
                   "kind_label": KIND_LABELS.get(o.source_type, o.source_type),
                   "url": f"{offers._URLS[o.source_type]}{o.source_id}"},
        "counterparty": None if o.counterparty is None else {
            "id": str(o.counterparty_id),
            "name": counterparties.display_name(o.counterparty)},
        "currency_code": o.currency_code, "amount": _text(o.amount),
        "amount_kzt": _text(o.amount_kzt), "source_amount_kzt": _text(o.source_amount_kzt),
        "saving_amount": _text(o.saving_amount), "saving_pct": _text(o.saving_pct),
        "more_expensive": o.saving_amount is not None and o.saving_amount < 0,
        "created_at": o.created_at, "submitted_at": o.submitted_at,
        "decided_at": o.decided_at,
    } for o in chunk]
    return {"items": items, "total": total, "page": page, "page_size": page_size}
