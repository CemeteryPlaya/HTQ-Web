"""Разбор и проверка условий ветвления — чистый модуль, без БД.

``services/conditions.py`` не трогает ни ORM, ни реестр, поэтому тесты здесь
работают на самодельных заглушках этапов и обходятся без ``django_db``. Всё,
что требует настоящего маршрута и процесса, — в ``test_branching.py``.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal

import pytest

from apps.signoff.services import conditions
from apps.signoff.services.conditions import ConditionError, NoBranchMatched

FIELDS = [
    {"key": "zone", "label": "Зона", "type": "choice",
     "options": [{"value": 1, "label": "Первая"}, {"value": 2, "label": "Вторая"},
                 {"value": 3, "label": "Третья"}]},
    {"key": "amount", "label": "Сумма", "type": "number"},
    {"key": "currency", "label": "Валюта", "type": "string"},
    {"key": "urgent", "label": "Срочно", "type": "bool"},
]


@dataclass
class FakeStage:
    """Этап маршрута ровно в том объёме, который читает ``select_stages``."""

    pk: int
    order: int
    name: str
    condition: list = field(default_factory=list)
    is_fallback: bool = False


def zone(*values):
    return [{"field": "zone", "op": "in", "value": list(values)}]


# ═══════════════════════════════════════════════════════════════════════
# evaluate
# ═══════════════════════════════════════════════════════════════════════

def test_empty_condition_always_matches():
    assert conditions.evaluate([], {"zone": 1}) is True


@pytest.mark.parametrize("op,value,expected", [
    ("eq", 2, True), ("eq", 3, False),
    ("in", [1, 2], True), ("in", [3], False),
    ("not_in", [3], True), ("not_in", [2], False),
])
def test_set_operators(op, value, expected):
    predicate = [{"field": "zone", "op": op, "value": value}]
    assert conditions.evaluate(predicate, {"zone": 2}) is expected


@pytest.mark.parametrize("op,expected", [
    ("gt", True), ("gte", True), ("lt", False), ("lte", False)])
def test_order_operators(op, expected):
    predicate = [{"field": "amount", "op": op, "value": 100}]
    assert conditions.evaluate(predicate, {"amount": 500}) is expected


def test_predicates_are_anded():
    predicate = zone(1) + [{"field": "amount", "op": "gt", "value": 100}]
    assert conditions.evaluate(predicate, {"zone": 1, "amount": 500}) is True
    # Второй предикат не выполнен — всё условие ложно.
    assert conditions.evaluate(predicate, {"zone": 1, "amount": 50}) is False


def test_missing_fact_is_an_error_not_a_false():
    """Ключевое различие: сломанная настройка обязана кричать.

    Если маршрут спрашивает поле, которого объект не сообщает, считать
    условие ложным значило бы тихо выкинуть этап из согласования — ровно тот
    бесшумный пропуск, ради предотвращения которого модуль и написан.
    """
    with pytest.raises(ConditionError, match="не сообщает поле"):
        conditions.evaluate(zone(1), {"amount": 5})


def test_none_fact_is_a_false_not_an_error():
    """А вот отсутствие ЗНАЧЕНИЯ — это данные, и ветка просто не подходит."""
    assert conditions.evaluate(zone(1), {"zone": None}) is False


def test_order_operator_across_types_raises():
    """Смешение типов — не «условие не сошлось», а TypeError, если его не
    поймать: строка с числом в Python не сравнивается вовсе."""
    with pytest.raises(ConditionError, match="сравнивает числа с числами"):
        conditions.evaluate([{"field": "currency", "op": "gt", "value": 1}],
                            {"currency": "KZT"})


def test_order_operator_on_two_strings_is_lexicographic():
    assert conditions.evaluate(
        [{"field": "currency", "op": "gt", "value": "KZT"}],
        {"currency": "USD"}) is True


def test_bool_is_not_a_number_for_order_operators():
    """Иначе ``urgent > 0`` прошло бы как осмысленное сравнение."""
    with pytest.raises(ConditionError, match="сравнивает числа с числами"):
        conditions.evaluate([{"field": "urgent", "op": "gt", "value": 0}],
                            {"urgent": True})


@pytest.mark.parametrize("predicate,match", [
    ("не объект", "должен быть объектом"),
    ({"field": "zone", "op": "wat", "value": 1}, "Неизвестный оператор"),
    ({"op": "eq", "value": 1}, "не указано поле"),
    ({"field": "zone", "op": "in", "value": 1}, "непустой список"),
    ({"field": "zone", "op": "in", "value": []}, "непустой список"),
    ({"field": "zone", "op": "eq", "value": [1]}, "не список"),
    ({"field": "zone", "op": "eq", "value": 1, "лишнее": 1}, "Лишние ключи"),
])
def test_malformed_predicates(predicate, match):
    with pytest.raises(ConditionError, match=match):
        conditions.evaluate([predicate], {"zone": 1})


# ═══════════════════════════════════════════════════════════════════════
# normalize_facts
# ═══════════════════════════════════════════════════════════════════════

def test_decimal_becomes_float():
    """``JSONField`` не умеет Decimal, а факты не только сравниваются, но и
    сохраняются в ``ApprovalProcess.subject_facts``."""
    assert conditions.normalize_facts({"amount": Decimal("10.50")}) == {"amount": 10.5}


def test_dates_become_iso_strings():
    facts = conditions.normalize_facts({"signed": dt.date(2026, 7, 30)})
    assert facts == {"signed": "2026-07-30"}
    # Лексикографический порядок ISO совпадает с хронологическим, поэтому
    # порядковые операторы на датах продолжают работать.
    assert conditions.evaluate(
        [{"field": "signed", "op": "gt", "value": "2026-01-01"}], facts) is True
    assert conditions.evaluate(
        [{"field": "signed", "op": "lt", "value": "2026-01-01"}], facts) is False


def test_non_scalar_fact_is_rejected():
    with pytest.raises(ConditionError, match="неподдерживаемый тип"):
        conditions.normalize_facts({"lines": [1, 2, 3]})


# ═══════════════════════════════════════════════════════════════════════
# validate — настройка маршрута
# ═══════════════════════════════════════════════════════════════════════

def test_validate_accepts_a_good_condition():
    assert conditions.validate(zone(1, 2), FIELDS) == zone(1, 2)


def test_validate_rejects_unknown_field():
    with pytest.raises(ConditionError, match="Неизвестное поле"):
        conditions.validate([{"field": "country", "op": "eq", "value": 1}], FIELDS)


def test_validate_rejects_value_outside_the_reference_book():
    """Опечатка в id страны обязана всплыть у того, кто настраивает."""
    with pytest.raises(ConditionError, match="неизвестные значения"):
        conditions.validate(zone(1, 99), FIELDS)


def test_validate_rejects_order_operator_on_choice():
    with pytest.raises(ConditionError, match="нельзя сравнивать"):
        conditions.validate([{"field": "zone", "op": "gt", "value": 1}], FIELDS)


def test_validate_rejects_wrong_value_type():
    with pytest.raises(ConditionError, match="ожидается число"):
        conditions.validate([{"field": "amount", "op": "gt", "value": "много"}],
                            FIELDS)


def test_validate_refuses_when_the_type_declares_no_fields():
    with pytest.raises(ConditionError, match="не объявлено ни одного поля"):
        conditions.validate(zone(1), [])


def test_empty_condition_needs_no_fields():
    """Тип без ветвления обязан продолжать принимать безусловные этапы."""
    assert conditions.validate([], []) == []


def test_validate_fields_rejects_choice_without_options():
    with pytest.raises(ConditionError, match="должно перечислить options"):
        conditions.validate_fields([{"key": "zone", "type": "choice"}])


def test_validate_fields_rejects_unknown_type():
    with pytest.raises(ConditionError, match="неизвестный тип"):
        conditions.validate_fields([{"key": "zone", "type": "магия"}])


# ═══════════════════════════════════════════════════════════════════════
# select_stages — собственно ветвление
# ═══════════════════════════════════════════════════════════════════════

def branching_route() -> list[FakeStage]:
    """Маршрут заказчика: двое проверяют → ветка по зоне → один утверждает."""
    return [
        FakeStage(1, 1, "Проверка"),
        FakeStage(2, 2, "Зона 1", condition=zone(1)),
        FakeStage(3, 2, "Зона 2", condition=zone(2)),
        FakeStage(4, 3, "Утверждение"),
    ]


def test_only_the_matching_branch_is_selected():
    selected = conditions.select_stages(branching_route(), {"zone": 2})
    assert [item.stage.name for item in selected] == \
        ["Проверка", "Зона 2", "Утверждение"]


def test_matched_by_records_why_each_stage_is_here():
    selected = conditions.select_stages(branching_route(), {"zone": 1})
    assert [item.matched_by for item in selected] == \
        [conditions.MATCH_ALWAYS, conditions.MATCH_CONDITION,
         conditions.MATCH_ALWAYS]


def test_unmatched_group_without_fallback_raises():
    """Зона 3 не описана ни одной веткой — запуск обязан отказать.

    Альтернатива (пропустить группу) означала бы, что документ третьей зоны
    тихо проходит мимо целого этапа согласования и никто этого не замечает.
    """
    with pytest.raises(NoBranchMatched) as exc:
        conditions.select_stages(branching_route(), {"zone": 3})
    assert exc.value.order == 2
    assert exc.value.facts == {"zone": 3}


def test_fallback_covers_the_unmatched_group():
    stages = branching_route() + [FakeStage(5, 2, "Прочие зоны", is_fallback=True)]
    selected = conditions.select_stages(stages, {"zone": 3})
    assert [item.stage.name for item in selected] == \
        ["Проверка", "Прочие зоны", "Утверждение"]
    assert selected[1].matched_by == conditions.MATCH_FALLBACK


def test_fallback_stays_out_when_a_branch_matched():
    stages = branching_route() + [FakeStage(5, 2, "Прочие зоны", is_fallback=True)]
    selected = conditions.select_stages(stages, {"zone": 1})
    assert [item.stage.name for item in selected] == \
        ["Проверка", "Зона 1", "Утверждение"]


def test_several_branches_can_match_at_once():
    """Условия веток не обязаны быть взаимоисключающими: совпало две —
    обе идут параллельно, ровно как два обычных этапа одной очереди."""
    stages = [FakeStage(1, 1, "Зона 1 и 2", condition=zone(1, 2)),
              FakeStage(2, 1, "Только зона 1", condition=zone(1))]
    selected = conditions.select_stages(stages, {"zone": 1})
    assert len(selected) == 2


def test_unconditional_stage_keeps_a_group_alive():
    """Если в группе есть безусловный этап, несошедшаяся ветка рядом с ним —
    это нормальная настройка «иногда добавляется ещё одна проверка», а не
    дыра: группа не пуста, и падать не на чем."""
    stages = [FakeStage(1, 1, "Всегда"),
              FakeStage(2, 1, "Только зона 1", condition=zone(1))]
    selected = conditions.select_stages(stages, {"zone": 2})
    assert [item.stage.name for item in selected] == ["Всегда"]


def test_route_without_conditions_is_untouched():
    """Главная гарантия обратной совместимости: маршрут без условий проходит
    отбор целиком и в прежнем порядке."""
    stages = [FakeStage(1, 1, "Раз"), FakeStage(2, 1, "Два"), FakeStage(3, 2, "Три")]
    selected = conditions.select_stages(stages, {})
    assert [item.stage.name for item in selected] == ["Раз", "Два", "Три"]
    assert {item.matched_by for item in selected} == {conditions.MATCH_ALWAYS}


# ═══════════════════════════════════════════════════════════════════════
# coverage_gaps — подсказка редактору
# ═══════════════════════════════════════════════════════════════════════

def test_coverage_gap_names_the_uncovered_options():
    gaps = conditions.coverage_gaps(branching_route(), FIELDS)
    assert len(gaps) == 1
    assert gaps[0]["order"] == 2
    assert gaps[0]["field"] == "zone"
    assert [option["value"] for option in gaps[0]["missing"]] == [3]


def test_no_gap_when_a_fallback_closes_the_group():
    stages = branching_route() + [FakeStage(5, 2, "Прочие", is_fallback=True)]
    assert conditions.coverage_gaps(stages, FIELDS) == []


def test_no_gap_when_every_option_has_a_branch():
    stages = [FakeStage(1, 1, "Зона 1", condition=zone(1)),
              FakeStage(2, 1, "Зона 2 и 3", condition=zone(2, 3))]
    assert conditions.coverage_gaps(stages, FIELDS) == []


def test_no_gap_for_a_group_that_has_an_unconditional_stage():
    stages = [FakeStage(1, 1, "Всегда"), FakeStage(2, 1, "Зона 1", condition=zone(1))]
    assert conditions.coverage_gaps(stages, FIELDS) == []
