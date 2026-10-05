"""Отчёт R-01 «KPI снабжения» и записи KPI для перехода из его ячеек
(ТЗ §12.6, KPI-001…KPI-004; план этапа 5 A, задача 5).

Строка отчёта — покупатель (автор выбранных АП):

- ``submitted`` — его АП «Подано», «Выбрано», «Не выбрано» с ``submitted_at``
  в периоде; «Отозвано» и «Аннулировано» в знаменатель KPI-004 не входят;
- ``selected`` — записи KPI любого статуса с ``selected_at`` в периоде;
- ``confirmed`` (KPI-001) — записи «Подтверждён»;
- ``share_pct`` (KPI-004) — ``confirmed / submitted × 100``, 0,01 %,
  ``ROUND_HALF_UP``; при нуле подано — ``null``, не 0 %;
- ``saving`` (KPI-002) — Σ положительной экономии подтверждённых;
- ``overspend`` (KPI-003) — Σ модуля отрицательной, отдельно, из экономии
  не вычитается;
- ``own_document_count`` — записи с признаком «К своему документу» (BR-092).

Итоговая строка — по всем покупателям, роль видна отдельно (D-S5-9). СН
видит только свою строку и свои записи (ТЗ §12.6): ограничение — в самом
запросе, не в выводе. Период — по дате выбора (у «подано» — по дате подачи),
границы включительные, в поясе платформы.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db.models import Count, Max, Q, Sum
from django.db.models.functions import Abs

from apps.bpp.models import AlternativeOffer, KpiRecord, KpiStatus, OfferSource, OfferStatus
from apps.bpp.services.actor import Actor
from apps.bpp.services.alternatives import kpi as service
from apps.bpp.services.core import export
from apps.users import interface as users

__all__ = ["Filters", "REPORT_COLUMNS", "RECORD_COLUMNS", "export_book", "record_out",
           "records", "report"]

#: Учитываются в «подано» (знаменатель KPI-004).
SUBMITTED_STATUSES = (OfferStatus.SUBMITTED, OfferStatus.SELECTED, OfferStatus.NOT_SELECTED)
_ZERO = Decimal("0.00")
_PCT = Decimal("0.01")
_PAGE_MAX = 200

REPORT_COLUMNS = (
    export.Column("name", "Покупатель"),
    export.Column("role", "Роль"),
    export.Column("submitted", "Подано АП", "integer"),
    export.Column("selected", "Выбрано", "integer"),
    export.Column("confirmed", "Подтверждено (KPI-001)", "integer"),
    export.Column("share_pct", "Доля подтверждённых, % (KPI-004)", "decimal"),
    export.Column("saving", "Экономия, KZT (KPI-002)", "money"),
    export.Column("overspend", "Удорожание, KZT (KPI-003)", "money"),
    export.Column("own_document_count", "К своему документу", "integer"),
)
RECORD_COLUMNS = (
    export.Column("buyer_name", "Покупатель"),
    export.Column("buyer_role", "Роль"),
    export.Column("offer_number", "АП"),
    export.Column("source_number", "Исходный документ"),
    export.Column("result_number", "Новый документ"),
    export.Column("status_label", "Статус"),
    export.Column("source_amount_kzt", "Исходная часть, KZT", "money"),
    export.Column("result_amount_kzt", "Новый документ, KZT", "money"),
    export.Column("saving_amount", "Экономия, KZT", "money"),
    export.Column("saving_pct", "Экономия, %", "decimal"),
    export.Column("own_document", "К своему документу"),
    export.Column("selected_at", "Дата выбора", "datetime"),
    export.Column("annul_comment", "Причина аннулирования"),
)

_ROLE_LABELS = {"sn": "Снабженец", "pm": "Руководитель проекта"}


@dataclass(frozen=True)
class Filters:
    period_from: date | None = None
    period_to: date | None = None
    buyer_id: int | None = None
    project_id: str | None = None
    article_id: str | None = None
    status: str | None = None
    own_document: bool | None = None

    def echo(self) -> dict:
        return {"period_from": self.period_from.isoformat() if self.period_from else None,
                "period_to": self.period_to.isoformat() if self.period_to else None,
                "buyer_id": self.buyer_id, "project_id": self.project_id,
                "article_id": self.article_id, "status": self.status,
                "own_document": self.own_document}


def _bounds(f: Filters) -> tuple[datetime | None, datetime | None]:
    zone = ZoneInfo(settings.PLATFORM_TIME_ZONE)
    start = datetime.combine(f.period_from, time.min, tzinfo=zone) if f.period_from else None
    end = (datetime.combine(f.period_to + timedelta(days=1), time.min, tzinfo=zone)
           if f.period_to else None)
    return start, end


def _period(field: str, f: Filters) -> Q:
    start, end = _bounds(f)
    q = Q()
    if start:
        q &= Q(**{f"{field}__gte": start})
    if end:
        q &= Q(**{f"{field}__lt": end})
    return q


def _kpi_qs(actor: Actor, f: Filters):
    qs = KpiRecord.objects.filter(_period("selected_at", f))
    if not service.sees_all(actor):
        qs = qs.filter(buyer_id=actor.user_id)
    if f.buyer_id is not None:
        qs = qs.filter(buyer_id=f.buyer_id)
    if f.project_id:
        qs = qs.filter(project_id=f.project_id)
    if f.article_id:
        qs = qs.filter(article_id=f.article_id)
    if f.status:
        qs = qs.filter(status=f.status)
    if f.own_document is not None:
        qs = qs.filter(own_document=f.own_document)
    return qs


def _offer_qs(actor: Actor, f: Filters):
    qs = AlternativeOffer.objects.filter(status__in=SUBMITTED_STATUSES,
                                         submitted_at__isnull=False)
    qs = qs.filter(_period("submitted_at", f))
    if not service.sees_all(actor):
        qs = qs.filter(author_id=actor.user_id)
    if f.buyer_id is not None:
        qs = qs.filter(author_id=f.buyer_id)
    if f.project_id:
        qs = qs.filter(project_id=f.project_id)
    if f.article_id:
        qs = qs.filter(article_id=f.article_id)
    return qs


def _share(confirmed: int, submitted: int) -> Decimal | None:
    if not submitted:
        return None
    return (Decimal(confirmed) * 100 / Decimal(submitted)).quantize(_PCT, rounding=ROUND_HALF_UP)


def _names(ids) -> dict[int, str | None]:
    ids = list(ids)
    if not ids:
        return {}
    return {row["id"]: row.get("full_name") for row in users.get_users_brief(ids)}


def report(actor: Actor, f: Filters) -> dict:
    """R-01: ``{rows, total, filters}``. Деньги — строками."""
    confirmed = Q(status=KpiStatus.CONFIRMED)
    kpi_rows = {row["buyer_id"]: row for row in _kpi_qs(actor, f).values("buyer_id").annotate(
        role=Max("buyer_role"), selected=Count("id"),
        confirmed=Count("id", filter=confirmed),
        saving=Sum("saving_amount", filter=confirmed & Q(saving_amount__gt=0)),
        overspend=Sum(Abs("saving_amount"), filter=confirmed & Q(saving_amount__lt=0)),
        own=Count("id", filter=Q(own_document=True)))}
    offer_rows = {row["author_id"]: row for row in _offer_qs(actor, f).values("author_id")
                  .annotate(role=Max("author_role"), submitted=Count("id"))}
    names = _names({*kpi_rows, *offer_rows})
    rows = []
    for buyer_id in {*kpi_rows, *offer_rows}:
        k, o = kpi_rows.get(buyer_id, {}), offer_rows.get(buyer_id, {})
        rows.append(_row(buyer_id, names.get(buyer_id) or f"Пользователь {buyer_id}",
                         k.get("role") or o.get("role") or "",
                         o.get("submitted", 0), k.get("selected", 0), k.get("confirmed", 0),
                         k.get("saving"), k.get("overspend"), k.get("own", 0)))
    rows.sort(key=lambda row: (row["name"].lower(), row["buyer_id"]))
    total = _row(None, "Итого", "", sum(r["submitted"] for r in rows),
                 sum(r["selected"] for r in rows), sum(r["confirmed"] for r in rows),
                 sum((Decimal(r["saving"]) for r in rows), _ZERO),
                 sum((Decimal(r["overspend"]) for r in rows), _ZERO),
                 sum(r["own_document_count"] for r in rows))
    return {"rows": rows, "total": total, "filters": f.echo()}


def _row(buyer_id, name, role, submitted, selected, confirmed, saving, overspend, own) -> dict:
    share = _share(confirmed, submitted)
    return {"buyer_id": buyer_id, "name": name, "role": role,
            "role_label": _ROLE_LABELS.get(role, ""), "submitted": submitted,
            "selected": selected, "confirmed": confirmed,
            "share_pct": str(share) if share is not None else None,
            "saving": str(saving or _ZERO), "overspend": str(overspend or _ZERO),
            "own_document_count": own}


# ── записи ──────────────────────────────────────────────────────────────

def _url(doc_type: str, doc_id) -> str:
    kind = "invoices" if doc_type == OfferSource.INVOICE else "agreements"
    return f"/bpp/{kind}/{doc_id}"


def _s(value) -> str | None:
    return None if value is None else str(value)


def record_out(kpi: KpiRecord, names: dict[int, str | None]) -> dict:
    return {
        "id": str(kpi.pk), "version": kpi.version, "offer_id": str(kpi.offer_id),
        "offer_number": kpi.offer.number, "offer_url": f"/bpp/alternatives/{kpi.offer_id}",
        "buyer_id": kpi.buyer_id,
        "buyer_name": names.get(kpi.buyer_id) or f"Пользователь {kpi.buyer_id}",
        "buyer_role": kpi.buyer_role, "own_document": kpi.own_document,
        "project_id": str(kpi.project_id), "article_id": str(kpi.article_id),
        "source_type": kpi.source_type, "source_id": str(kpi.source_id),
        "source_number": kpi.source_number, "source_url": _url(kpi.source_type, kpi.source_id),
        "source_counterparty_id": _s(kpi.source_counterparty_id),
        "source_amount_kzt": str(kpi.source_amount_kzt),
        "result_type": kpi.result_type, "result_id": str(kpi.result_id),
        "result_number": kpi.result_number, "result_url": _url(kpi.result_type, kpi.result_id),
        "result_amount_kzt": _s(kpi.result_amount_kzt),
        "saving_amount": _s(kpi.saving_amount), "saving_pct": _s(kpi.saving_pct),
        "status": kpi.status, "status_label": kpi.get_status_display(),
        "status_changed_at": kpi.status_changed_at.isoformat() if kpi.status_changed_at
        else None,
        "selected_at": kpi.selected_at.isoformat(), "selected_by_id": kpi.selected_by_id,
        "annul_comment": kpi.annul_comment, "annulled_by_id": kpi.annulled_by_id,
    }


def _rows(qs) -> list[dict]:
    items = list(qs.select_related("offer"))
    names = _names({item.buyer_id for item in items})
    return [record_out(item, names) for item in items]


def records(actor: Actor, f: Filters, *, limit: int = 50, offset: int = 0) -> dict:
    """Записи KPI для перехода из ячейки отчёта: ``{items, total}``."""
    qs = _kpi_qs(actor, f)
    limit = max(1, min(int(limit), _PAGE_MAX))
    offset = max(0, int(offset))
    return {"items": _rows(qs.order_by("-selected_at", "id")[offset:offset + limit]),
            "total": qs.count(), "filters": f.echo()}


def card(actor: Actor, kpi_id) -> dict:
    kpi = service.get_visible(actor, kpi_id)
    return _rows(KpiRecord.objects.filter(pk=kpi.pk))[0]


def export_book(actor: Actor, f: Filters) -> bytes:
    """Книга xlsx: «KPI снабжения» (строки отчёта и итог) и «Записи KPI»;
    суммы — числами. Права и охват — те же, что у ручек."""
    data = report(actor, f)
    lines = []
    for row in (*data["rows"], data["total"]):
        lines.append({**row, "role": row["role_label"] or row["role"]})
    recs = _rows(_kpi_qs(actor, f).order_by("-selected_at", "id"))
    for rec in recs:
        rec["own_document"] = "Да" if rec["own_document"] else ""
        rec["buyer_role"] = _ROLE_LABELS.get(rec["buyer_role"], rec["buyer_role"])
    return export.write_xlsx_sheets("KPI снабжения", [
        ("KPI снабжения", REPORT_COLUMNS, lines),
        ("Записи KPI", RECORD_COLUMNS, recs)], limit=export.HARD_LIMIT)
