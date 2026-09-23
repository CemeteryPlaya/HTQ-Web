"""``PositionAdmin`` не должен оставаться путём записи ``hr_level``.

Фикс-раунд 1 задачи 10 блока I.2 (находка Info-3 ревью, `task-10-review.md`):
API должностей с задачи 10 больше не принимает ``hr_level`` (Pydantic
``extra="ignore"`` отбрасывает ключ при парсинге), но django-admin правит
``Position.permissions`` сырым JSON-виджетом ``ModelAdmin`` — в обход схемы
целиком. Это единственный оставшийся путь, которым в колонку мог бы попасть
``hr_level`` ПОСЛЕ переноса — ровно то, от чего задача 10 должна была
защитить (обоснование брифа: «иначе значение, выставленное уже ПОСЛЕ
переноса, подхватил бы повторный ``access_backfill_positions``»).
``PositionAdmin.save_model`` (``apps/hr/admin.py``) теперь отбрасывает ключ
``hr_level`` из ``permissions`` при каждом сохранении, оставляя список
``permissions`` (ключи ``contracts.*``) редактируемым как был.
"""
from __future__ import annotations

import pytest
from django.contrib.admin.sites import AdminSite

from apps.hr.admin import PositionAdmin
from apps.hr.models import Department, Position


@pytest.fixture
def dep(db):
    return Department.objects.create(name="Бухгалтерия", path="buh")


@pytest.mark.django_db
def test_admin_save_drops_hr_level_from_permissions(dep):
    """Сохранение через админку с ``hr_level`` в теле — hr_level не остаётся."""
    admin = PositionAdmin(Position, AdminSite())
    contracts_key = "contracts.advance_payment.record_payment"
    obj = Position(
        title="Кадровик", department=dep, weight=50,
        permissions={"hr_level": "lead", "permissions": [contracts_key]},
    )

    admin.save_model(request=None, obj=obj, form=None, change=False)

    saved = Position.objects.get(id=obj.id)
    assert "hr_level" not in (saved.permissions or {})
    assert saved.permissions["permissions"] == [contracts_key]


@pytest.mark.django_db
def test_admin_save_keeps_permissions_list_editable(dep):
    """Список ключей (ради ``contracts.*``) остаётся редактируемым — не readonly."""
    admin = PositionAdmin(Position, AdminSite())
    pos = Position.objects.create(
        title="Бухгалтер", department=dep, weight=51,
        permissions={"permissions": ["contracts.advance_payment.record_payment"]},
    )
    pos.permissions = {"permissions": ["contracts.budget.approve"]}

    admin.save_model(request=None, obj=pos, form=None, change=True)

    pos.refresh_from_db()
    assert pos.permissions == {"permissions": ["contracts.budget.approve"]}


@pytest.mark.django_db
def test_admin_save_without_permissions_does_not_crash(dep):
    """``permissions is None`` — обычное состояние новой должности, не падает."""
    admin = PositionAdmin(Position, AdminSite())
    obj = Position(title="Стажёр", department=dep, weight=52)

    admin.save_model(request=None, obj=obj, form=None, change=False)

    saved = Position.objects.get(id=obj.id)
    assert saved.permissions is None
