"""Правила матрицы замещения.

Главное правило одно: у должности не может быть двух одновременно
действующих замещающих одного вида. Иначе маршрут согласования получает
двух «основных» и молча выбирает первого попавшегося — то есть решение
принимает порядок строк в таблице.
"""

from __future__ import annotations

import datetime as dt

import pytest

from apps.hr.models import Department, Position, SubstitutionKind
from apps.hr.services import substitution_service as svc

TODAY = dt.date(2026, 9, 16)


@pytest.fixture
def positions(db):
    dep = Department.objects.create(name="Руководство", path="upr")
    return {
        "ceo": Position.objects.create(title="Генеральный директор", department=dep, weight=10),
        "ops": Position.objects.create(title="Операционный директор", department=dep, weight=130),
        "cfo": Position.objects.create(title="Финансовый директор", department=dep, weight=110),
    }


def _create(positions, who="ceo", sub="ops", kind=SubstitutionKind.PRIMARY,
            valid_from=dt.date(2026, 1, 1), valid_to=None, basis="Приказ ГД"):
    return svc.create(
        position_id=positions[who].id, substitute_position_id=positions[sub].id,
        kind=kind, basis=basis, note=None, valid_from=valid_from, valid_to=valid_to,
    )


def test_create_returns_a_row_and_serializes_it(positions):
    row = _create(positions, basis="Приказ ГД; доверенность на банк")
    body = svc.serialize(row)
    assert body["position_id"] == positions["ceo"].id
    assert body["substitute_position_id"] == positions["ops"].id
    assert body["substitute_position_title"] == "Операционный директор"
    assert body["kind"] == "primary"
    assert body["basis"] == "Приказ ГД; доверенность на банк"
    assert body["valid_from"] == "2026-01-01"
    assert body["valid_to"] is None


def test_self_substitution_is_refused(positions):
    with pytest.raises(svc.SubstitutionSelfReferential):
        svc.create(position_id=positions["ceo"].id,
                   substitute_position_id=positions["ceo"].id,
                   kind=SubstitutionKind.PRIMARY, basis="Приказ ГД", note=None,
                   valid_from=TODAY, valid_to=None)


@pytest.mark.parametrize("field", ["position_id", "substitute_position_id"])
def test_unknown_position_is_refused(positions, field):
    kwargs = dict(position_id=positions["ceo"].id,
                  substitute_position_id=positions["ops"].id,
                  kind=SubstitutionKind.PRIMARY, basis="Приказ ГД", note=None,
                  valid_from=TODAY, valid_to=None)
    kwargs[field] = 10_000_000
    with pytest.raises(svc.SubstitutionPositionNotFound):
        svc.create(**kwargs)


def test_two_open_ended_primaries_overlap(positions):
    _create(positions, valid_from=dt.date(2026, 1, 1))
    with pytest.raises(svc.SubstitutionOverlap):
        _create(positions, sub="cfo", valid_from=dt.date(2026, 6, 1))


def test_closed_period_lets_the_next_one_start(positions):
    _create(positions, valid_from=dt.date(2026, 1, 1), valid_to=dt.date(2026, 5, 31))
    row = _create(positions, sub="cfo", valid_from=dt.date(2026, 6, 1))
    assert row.valid_from == dt.date(2026, 6, 1)


def test_periods_touching_on_the_same_day_overlap(positions):
    """Границы включительные: правило, действующее ПО 31 мая, и правило,
    действующее С 31 мая, в этот день оба активны."""
    _create(positions, valid_from=dt.date(2026, 1, 1), valid_to=dt.date(2026, 5, 31))
    with pytest.raises(svc.SubstitutionOverlap):
        _create(positions, sub="cfo", valid_from=dt.date(2026, 5, 31))


def test_reserve_does_not_collide_with_primary(positions):
    _create(positions, kind=SubstitutionKind.PRIMARY, valid_from=dt.date(2026, 1, 1))
    row = _create(positions, sub="cfo", kind=SubstitutionKind.RESERVE,
                  valid_from=dt.date(2026, 1, 1))
    assert row.kind == "reserve"


def test_update_rechecks_the_overlap_without_colliding_with_itself(positions):
    row = _create(positions, valid_from=dt.date(2026, 1, 1), valid_to=dt.date(2026, 5, 31))
    # Своя же строка не должна считаться пересечением самой себя.
    updated = svc.update(row.id, valid_to=dt.date(2026, 6, 30))
    assert updated.valid_to == dt.date(2026, 6, 30)

    other = _create(positions, sub="cfo", valid_from=dt.date(2026, 7, 1))
    with pytest.raises(svc.SubstitutionOverlap):
        svc.update(other.id, valid_from=dt.date(2026, 6, 1))


def test_delete_removes_the_row_and_unknown_id_is_refused(positions):
    row = _create(positions)
    svc.delete(row.id)
    assert svc.list_for_position(positions["ceo"].id) == []
    with pytest.raises(svc.SubstitutionNotFound):
        svc.delete(row.id)


def test_list_puts_primary_first_then_newest_period(positions):
    old = _create(positions, valid_from=dt.date(2025, 1, 1), valid_to=dt.date(2025, 12, 31))
    new = _create(positions, sub="cfo", valid_from=dt.date(2026, 1, 1))
    reserve = _create(positions, sub="cfo", kind=SubstitutionKind.RESERVE,
                      valid_from=dt.date(2026, 1, 1))
    assert [r.id for r in svc.list_for_position(positions["ceo"].id)] == [
        new.id, old.id, reserve.id]


def test_active_for_position_filters_by_date(positions):
    past = _create(positions, valid_from=dt.date(2025, 1, 1), valid_to=dt.date(2025, 12, 31))
    now = _create(positions, sub="cfo", valid_from=dt.date(2026, 1, 1))
    active = svc.active_for_position(positions["ceo"].id, TODAY)
    assert [r.id for r in active] == [now.id]
    assert [r.id for r in svc.active_for_position(positions["ceo"].id,
                                                  dt.date(2025, 6, 1))] == [past.id]


def test_active_for_position_skips_a_deactivated_substitute(positions):
    """Неактивная должность никого не прикроет — вернуть её значит отправить
    маршрут согласования в тупик."""
    _create(positions)
    positions["ops"].is_active = False
    positions["ops"].save(update_fields=["is_active", "updated_at"])
    assert svc.active_for_position(positions["ceo"].id, TODAY) == []
