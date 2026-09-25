"""Матрица замещения (HR-FRM-006) на уровне схемы.

Замещающий — ДОЛЖНОСТЬ, а не человек: документ составлен по должностям, и
только так правило переживает смену держателя. Ограничения в БД закрывают
то, что нельзя доверить дисциплине вызывающего: замещение самого себя и
период, кончающийся раньше, чем начался.
"""

from __future__ import annotations

import datetime as dt

import pytest
from django.db import IntegrityError, transaction

from apps.hr.models import Department, Position, Substitution, SubstitutionKind


@pytest.fixture
def dep(db):
    return Department.objects.create(name="Руководство", path="upr")


def _pos(dep, title, weight):
    return Position.objects.create(title=title, department=dep, weight=weight)


@pytest.mark.django_db
def test_substitution_stores_the_document_row(dep):
    ceo = _pos(dep, "Генеральный директор", 10)
    ops = _pos(dep, "Операционный директор", 130)
    row = Substitution.objects.create(
        position=ceo, substitute_position=ops, kind=SubstitutionKind.PRIMARY,
        basis="Приказ ГД / решение участника; доверенность",
        note="Право первой подписи по доверенности",
        valid_from=dt.date(2026, 9, 10),
    )
    row.refresh_from_db()
    assert row.kind == "primary"
    assert row.valid_to is None  # бессрочно, пока приказ не отменён
    assert row.get_kind_display() == "Основной"
    assert list(ceo.substitutions.all()) == [row]
    assert list(ops.substitutes_in.all()) == [row]


@pytest.mark.django_db
def test_position_cannot_substitute_itself(dep):
    ceo = _pos(dep, "Генеральный директор", 10)
    with pytest.raises(IntegrityError), transaction.atomic():
        Substitution.objects.create(
            position=ceo, substitute_position=ceo, basis="Приказ ГД",
            valid_from=dt.date(2026, 9, 10),
        )


@pytest.mark.django_db
def test_period_cannot_end_before_it_starts(dep):
    ceo = _pos(dep, "Генеральный директор", 10)
    ops = _pos(dep, "Операционный директор", 130)
    with pytest.raises(IntegrityError), transaction.atomic():
        Substitution.objects.create(
            position=ceo, substitute_position=ops, basis="Приказ ГД",
            valid_from=dt.date(2026, 9, 10), valid_to=dt.date(2026, 9, 1),
        )


@pytest.mark.django_db
def test_same_kind_cannot_start_twice_on_one_day(dep):
    """Два «основных» замещающих с одной датой начала — это не история, а
    ошибка ввода; пересечения периодов ловит сервис, точное совпадение —
    база."""
    ceo = _pos(dep, "Генеральный директор", 10)
    ops = _pos(dep, "Операционный директор", 130)
    cfo = _pos(dep, "Финансовый директор", 110)
    Substitution.objects.create(position=ceo, substitute_position=ops,
                                basis="Приказ ГД", valid_from=dt.date(2026, 9, 10))
    with pytest.raises(IntegrityError), transaction.atomic():
        Substitution.objects.create(position=ceo, substitute_position=cfo,
                                    basis="Приказ ГД", valid_from=dt.date(2026, 9, 10))


@pytest.mark.django_db
def test_reserve_may_start_the_same_day_as_primary(dep):
    """Основной и резервный — разные виды, один приказ заводит оба сразу."""
    ceo = _pos(dep, "Генеральный директор", 10)
    ops = _pos(dep, "Операционный директор", 130)
    cfo = _pos(dep, "Финансовый директор", 110)
    Substitution.objects.create(position=ceo, substitute_position=ops,
                                kind=SubstitutionKind.PRIMARY,
                                basis="Приказ ГД", valid_from=dt.date(2026, 9, 10))
    Substitution.objects.create(position=ceo, substitute_position=cfo,
                                kind=SubstitutionKind.RESERVE,
                                basis="Приказ ГД", valid_from=dt.date(2026, 9, 10))
    assert ceo.substitutions.count() == 2


@pytest.mark.django_db
def test_deleting_the_position_takes_its_rules_with_it(dep):
    """Правило замещения не переживает должность, к которой относится —
    тот же выбор, что у ReportingRelation."""
    ceo = _pos(dep, "Генеральный директор", 10)
    ops = _pos(dep, "Операционный директор", 130)
    Substitution.objects.create(position=ceo, substitute_position=ops,
                                basis="Приказ ГД", valid_from=dt.date(2026, 9, 10))
    ceo.delete()
    assert Substitution.objects.count() == 0
