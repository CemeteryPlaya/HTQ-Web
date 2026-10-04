"""Ручка «Сводка группы по БЗО» ``GET /api/bpp/v1/holding/summary`` (A8.1, D-S7-8).

Три замка: гейт модуля ``bpp`` (``read``) → узел ``bpp.holding`` view (ФД, ГД;
``EXPLICIT_ONLY``) → вид компании «холдинг» (``companies.is_holding``): на
поддомене дочерней компании сводка по группе — чужие цифры, даже у директора,
несущего там роли по наследованию. Платформенный администратор проходит вид
компании (как у ``tasks``/``hr``), узел ему не нужен. Во время
``migrate_companies`` представлений нет — 503 «пересобираются», не нули.
Подмодуля нет: путь ``holding`` не входит ни в один префикс ``bpp_*``.
"""

from __future__ import annotations

from apps.companies import interface as companies
from htqweb.errors import DomainError
from htqweb.http import api_view, json_error
from htqweb.tenancy.context import current_company_or_none

from .services.actor import Actor
from .services.holding import summary

HOLDING_NODE = "bpp.holding"


@api_view(methods=("GET",), module="bpp", level="read")
def holding_summary(request):
    actor = Actor(request)
    if not actor.can(HOLDING_NODE, "view"):
        raise DomainError("E-ACC-01", "У вас нет прав: сводка группы по модулю. Если это "
                                      "ошибка, обратитесь к администратору.", status=403)
    if not actor.is_superuser:
        slug = current_company_or_none()
        if not (slug and companies.is_holding(slug)):
            return json_error("Сводка по группе доступна только на поддомене холдинга", 403)
    try:
        return summary.summary()
    except summary.HoldingViewsUnavailable as exc:
        return json_error(str(exc), 503)
