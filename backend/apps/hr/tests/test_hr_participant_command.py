"""``hr_participant`` — боевой способ завести ОСУ в компании.

Команда обязана писать ТОЛЬКО туда, куда её явно направили: ``--company``
обязателен, умолчания на текущий ``search_path`` нет — на бою ``public``
это не компания, и молчаливая запись туда была бы подменой данных.
"""

from __future__ import annotations

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.hr.models import Department, Position


def _run(**kwargs):
    call_command("hr_participant", verbosity=0, **kwargs)


def test_company_is_required(db):
    with pytest.raises(CommandError):
        _run()


def test_unknown_company_is_refused(db):
    with pytest.raises(CommandError, match="не найдена"):
        _run(company="t-no-such-company")


def test_company_without_schema_is_refused(db):
    from apps.companies.models import Company, CompanyKind
    Company.objects.create(slug="t-orphan", name="Сирота", kind=CompanyKind.HOLDING)
    with pytest.raises(CommandError, match="схем"):
        _run(company="t-orphan")


def test_creates_the_participant_in_the_company_schema(company_schema, capsys):
    from htqweb.tenancy.db import use_company

    call_command("hr_participant", company=company_schema["slug"], verbosity=1)
    out = capsys.readouterr().out
    assert "заведена" in out
    with use_company(company_schema["slug"]):
        position = Position.objects.get(title="Участник (ОСУ)")
        assert position.is_system is True
        assert position.department.path == "osu"
    # public не тронут.
    assert not Position.objects.filter(title="Участник (ОСУ)").exists()
    assert not Department.objects.filter(path="osu").exists()


def test_second_run_reports_repair_not_creation(company_schema, capsys):
    call_command("hr_participant", company=company_schema["slug"], verbosity=1)
    capsys.readouterr()
    call_command("hr_participant", company=company_schema["slug"], verbosity=1)
    out = capsys.readouterr().out
    assert "уже есть" in out
    from htqweb.tenancy.db import use_company
    with use_company(company_schema["slug"]):
        assert Position.objects.filter(title="Участник (ОСУ)").count() == 1


def test_weight_conflict_is_a_readable_error(company_schema):
    from htqweb.tenancy.db import use_company

    with use_company(company_schema["slug"]):
        dep = Department.objects.create(name="Руководство", path="upr")
        Position.objects.create(title="Председатель", department=dep, weight=0)
    with pytest.raises(CommandError, match="Председатель"):
        _run(company=company_schema["slug"])
