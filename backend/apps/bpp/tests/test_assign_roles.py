"""bpp_assign_roles: должности холдинга получают роли модуля."""

import pytest
from django.core.management import call_command

from apps.access.models import PositionRole
from apps.hr.models import Department, Position


@pytest.mark.django_db
def test_positions_get_roles(company_context):
    dep = Department.objects.create(name="Финансы", path="fin")
    fd = Position.objects.create(title="Финансовый директор", department=dep, weight=110)
    buh = Position.objects.create(title="Главный бухгалтер", department=dep, weight=610)
    call_command("bpp_assign_roles", "--company", company_context["slug"])
    given = set(PositionRole.objects.values_list("position_id", "role__code"))
    assert {(fd.id, "bpp-fd"), (buh.id, "bpp-buh")} <= given
    call_command("bpp_assign_roles", "--company", company_context["slug"])  # идемпотентно
    assert PositionRole.objects.filter(role__code="bpp-fd").count() == 1
