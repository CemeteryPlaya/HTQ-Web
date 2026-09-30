"""Ручка дашборда D-01 «Оплаты» ``GET /api/bpp/v1/dashboard/payments`` (ТЗ
§11.5, §23 GetPaymentDashboard, REQ-018; план этапа 4 A, задача 5 — A4.3).

Гейт модуля ``bpp`` (``read``) и узел ``bpp.dashboard`` view (ФД, ТД, ОД,
ГД, БУХ — матрица ролей), иначе 403 ``E-ACC-01``. Подмодуля нет: путь
``dashboard`` не входит ни в один префикс ``bpp_*``
(``htqweb/middleware/service_gate.py``), рубильник — только у модуля.

Параметры: ``period_from``/``period_to`` (ГГГГ-ММ-ДД, дата платежа в
выписке), ``project_id``, ``article_id``, ``counterparty_id`` (UUID),
``author_id`` (целое). Неверное значение — 422 ``E-VAL-01`` на поле.
"""

from __future__ import annotations

from datetime import date

from htqweb.errors import DomainError
from htqweb.http import api_view

from .services.actor import Actor
from .services.budget.read import uuid_param
from .services.dashboard import payments
from .services.params import int_param

DASHBOARD_NODE = "bpp.dashboard"


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


def _filters(params) -> payments.Filters:
    period_from, period_to = _date(params, "period_from"), _date(params, "period_to")
    if period_from and period_to and period_from > period_to:
        raise DomainError("E-VAL-01", "Дата «по» раньше даты «с».",
                          fields=[{"field": "period_to", "message": "Раньше даты «с»"}])
    return payments.Filters(
        period_from=period_from, period_to=period_to,
        project_id=_uuid(params, "project_id"), article_id=_uuid(params, "article_id"),
        counterparty_id=_uuid(params, "counterparty_id"),
        author_id=int_param(params, "author_id"))


@api_view(methods=("GET",), module="bpp", level="read")
def payments_dashboard(request):
    actor = Actor(request)
    if not actor.can(DASHBOARD_NODE, "view"):
        raise DomainError("E-ACC-01", "У вас нет прав: просмотр дашборда оплат. Если это "
                                      "ошибка, обратитесь к администратору.", status=403)
    return payments.dashboard(actor, _filters(request.GET))
