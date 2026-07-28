"""Аппка отключается на ходу, как и все остальные (инвариант №8).

Два независимых слоя, оба обязаны отдать 503:
- HTTP-край — ``ServiceGateMiddleware`` по префиксу ``/api/contracts/``;
- внутрипроцессный вызов из соседа — ``require_service`` в ``interface.py``.
"""

import pytest
from django.core.cache import cache
from django.test import Client

from apps.contracts import interface
from apps.core.models import ServiceStatus
from apps.core.services import ServiceDisabled

from .helpers import BASE, auth, make_budget, token


@pytest.mark.django_db
def test_http_edge_returns_503_when_disabled():
    ServiceStatus.objects.update_or_create(
        app_label="contracts",
        defaults={"enabled": False, "message": "Модуль договоров на обслуживании"},
    )
    resp = Client().get(f"{BASE}/budgets", **auth(token()))
    assert resp.status_code == 503
    body = resp.json()
    assert body["code"] == "service_disabled"
    assert body["service"] == "contracts"


@pytest.mark.django_db
def test_interface_raises_service_disabled():
    budget = make_budget()
    # Пока аппка включена — обычный ответ.
    assert interface.get_budget_summary(budget.pk)["remaining"] is not None

    ServiceStatus.objects.update_or_create(
        app_label="contracts", defaults={"enabled": False},
    )
    # Первый (успешный) вызов выше положил "enabled" в 5-секундный кэш
    # service_status(). В проде переключатель подхватывается по истечении TTL;
    # в тесте ждать нечего — сбрасываем кэш явно, иначе проверялся бы срок
    # жизни кэша, а не гейт.
    cache.clear()

    with pytest.raises(ServiceDisabled):
        interface.get_budget_summary(budget.pk)
