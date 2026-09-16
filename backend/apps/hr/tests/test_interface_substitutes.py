"""Контракт `hr.substitutes_for` — то, что вызывает соседний домен.

Форма ответа зафиксирована в roadmap §6.1 и согласована с разработчиком
signoff: РОВНО три ключа. Лишний ключ здесь — это лишний ключ в чужом коде,
поэтому набор проверяется точным сравнением, а не вхождением.
"""

from __future__ import annotations

import datetime as dt

import pytest

from apps.core.services import ServiceDisabled
from apps.hr import interface
from apps.hr.models import Department, Position, SubstitutionKind
from apps.hr.services import substitution_service as svc

TODAY = dt.date(2026, 9, 16)


@pytest.fixture
def matrix(db):
    dep = Department.objects.create(name="Руководство", path="upr")
    ceo = Position.objects.create(title="Генеральный директор", department=dep, weight=10)
    ops = Position.objects.create(title="Операционный директор", department=dep, weight=130)
    cfo = Position.objects.create(title="Финансовый директор", department=dep, weight=110)
    svc.create(position_id=ceo.id, substitute_position_id=ops.id,
               kind=SubstitutionKind.PRIMARY,
               basis="Приказ ГД / решение участника; доверенность", note=None,
               valid_from=dt.date(2026, 1, 1), valid_to=None)
    svc.create(position_id=ceo.id, substitute_position_id=cfo.id,
               kind=SubstitutionKind.RESERVE, basis="Приказ ГД", note=None,
               valid_from=dt.date(2026, 1, 1), valid_to=None)
    return {"ceo": ceo, "ops": ops, "cfo": cfo}


def test_returns_exactly_the_agreed_keys(matrix):
    rows = interface.substitutes_for(matrix["ceo"].id, TODAY)
    assert [set(r) for r in rows] == [{"position_id", "kind", "basis"}] * 2


def test_primary_comes_first(matrix):
    rows = interface.substitutes_for(matrix["ceo"].id, TODAY)
    assert [r["kind"] for r in rows] == ["primary", "reserve"]
    assert rows[0]["position_id"] == matrix["ops"].id
    assert rows[0]["basis"] == "Приказ ГД / решение участника; доверенность"


def test_date_defaults_to_today(matrix):
    assert interface.substitutes_for(matrix["ceo"].id) == \
        interface.substitutes_for(matrix["ceo"].id, dt.date.today())


def test_position_without_rules_returns_empty_list(matrix):
    assert interface.substitutes_for(matrix["ops"].id, TODAY) == []


def test_unknown_position_returns_empty_list_not_an_error(matrix):
    """Сосед спрашивает про должность, которой в ЭТОЙ компании нет — это
    нормальный ответ «замещающих нет», а не отказ."""
    assert interface.substitutes_for(10_000_000, TODAY) == []


def test_expired_rule_is_not_returned(matrix):
    rows = interface.substitutes_for(matrix["ceo"].id, dt.date(2025, 1, 1))
    assert rows == []


def test_disabled_hr_refuses(matrix, monkeypatch):
    """Первая строка любой функции interface — require_service."""
    from apps.core import services as core_services

    monkeypatch.setattr(core_services, "service_status",
                        lambda name: (False, "выключено для проверки"))
    with pytest.raises(ServiceDisabled):
        interface.substitutes_for(matrix["ceo"].id, TODAY)
