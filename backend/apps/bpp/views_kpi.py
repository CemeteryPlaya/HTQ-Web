"""Ручки «KPI снабжения» ``/api/bpp/v1/kpi/…`` (ТЗ §12.5–12.6, R-01; план
этапа 5 A, задача 5 — A5.2). Подмодуль ``bpp_alternatives``.

Права — по узлу ``bpp.kpi`` (матрица ролей): ``view`` — отчёт, записи,
выгрузка (ФД, ОД, ГД; СН — только свои строки и записи, чужая запись — 404);
``edit`` — аннулирование (ФД). ТД, БУХ и ПМ узла не имеют — 403 ``E-ACC-01``.

Параметры отчёта и записей: ``period_from``/``period_to`` (ГГГГ-ММ-ДД, по
дате выбора), ``buyer_id``, ``project_id``, ``article_id``; у записей ещё
``status`` (``preliminary|confirmed|annulled``), ``own_document`` (``1|0``),
``limit`` (до 200) и ``offset``. Неверное значение — 422 ``E-VAL-01``.
"""

from __future__ import annotations

from datetime import date

from htqweb.errors import DomainError
from htqweb.http import api_view, uuid_or_404

from .models import KpiStatus
from .schemas import kpi as schemas
from .services.actor import Actor
from .services.alternatives import kpi as service
from .services.alternatives import report
from .services.budget.read import uuid_param
from .services.core import export
from .services.params import int_param


def _date(params, name: str) -> date | None:
    raw = params.get(name) or None
    if raw is None:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        raise DomainError("E-VAL-01", "Дата — в формате ГГГГ-ММ-ДД.",
                          fields=[{"field": name, "message": "Дата ГГГГ-ММ-ДД"}]) from None


def _uuid(params, name: str) -> str | None:
    raw = params.get(name) or None
    return uuid_param(raw, name) if raw is not None else None


def _filters(params, *, records: bool = False) -> report.Filters:
    period_from, period_to = _date(params, "period_from"), _date(params, "period_to")
    if period_from and period_to and period_from > period_to:
        raise DomainError("E-VAL-01", "Дата «по» раньше даты «с».",
                          fields=[{"field": "period_to", "message": "Раньше даты «с»"}])
    status = own = None
    if records:
        status = params.get("status") or None
        if status is not None and status not in KpiStatus.values:
            raise DomainError("E-VAL-01", "Неизвестный статус записи KPI.",
                              fields=[{"field": "status", "message": "preliminary, "
                                                                     "confirmed, annulled"}])
        raw = params.get("own_document")
        if raw not in (None, ""):
            if raw not in ("0", "1", "true", "false"):
                raise DomainError("E-VAL-01", "Признак — 1 или 0.",
                                  fields=[{"field": "own_document", "message": "1 или 0"}])
            own = raw in ("1", "true")
    return report.Filters(
        period_from=period_from, period_to=period_to,
        buyer_id=int_param(params, "buyer_id"), project_id=_uuid(params, "project_id"),
        article_id=_uuid(params, "article_id"), status=status, own_document=own)


def _viewer(request) -> Actor:
    actor = Actor(request)
    if not actor.can(service.NODE, "view"):
        raise service._deny("просмотр KPI снабжения")
    return actor


@api_view(methods=("GET",), module="bpp", level="read")
def kpi_report(request):
    return report.report(_viewer(request), _filters(request.GET))


@api_view(methods=("GET",), module="bpp", level="read")
def kpi_report_export(request):
    actor = _viewer(request)
    data = report.export_book(actor, _filters(request.GET))
    return export.xlsx_response("KPI снабжения", data)


@api_view(methods=("GET",), module="bpp", level="read")
def kpi_records(request):
    actor = _viewer(request)
    return report.records(actor, _filters(request.GET, records=True),
                          limit=int_param(request.GET, "limit", 50, minimum=1),
                          offset=int_param(request.GET, "offset", 0, minimum=0))


@api_view(methods=("GET",), module="bpp", level="read")
def kpi_card(request, kpi_id):
    return report.card(Actor(request), uuid_or_404(kpi_id))


@api_view(methods=("POST",), module="bpp", level="write", body=schemas.KpiAnnul,
          idempotent=True)
def kpi_annul(request, kpi_id, data):
    actor = Actor(request)
    service.annul(actor, uuid_or_404(kpi_id), comment=data.comment,
                  expected_version=data.version)
    return report.card(actor, uuid_or_404(kpi_id))
