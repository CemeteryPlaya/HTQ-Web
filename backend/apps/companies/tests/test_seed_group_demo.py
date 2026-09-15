"""Стенд группы одной командой: порядок шагов и идемпотентность.

Настоящее заведение четырёх схем — ~4 минуты (по минуте на схему), поэтому
здесь оно подменяется строками реестра, а вызовы соседних сидов
записываются: проверяется ОРКЕСТРАЦИЯ (что, для кого, в каком порядке),
а не содержимое сидов — у тех свои тесты. Сквозной прогон — руками на
dev-базе (план блока D, задача 7).
"""

from __future__ import annotations

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.companies.management.commands import seed_group_demo as cmd
from apps.companies.models import Company, CompanyMembership


@pytest.fixture
def fake_provisioning(monkeypatch):
    """provision_company → только строка реестра; call_command → журнал."""
    calls: list[tuple[str, dict]] = []

    def provision(*, slug, name, kind, parent_slug=None, country=""):
        parent = Company.objects.get(slug=parent_slug) if parent_slug else None
        return Company.objects.create(slug=slug, name=name, kind=kind, parent=parent)

    def record(name, *args, **kwargs):
        calls.append((name, kwargs))

    monkeypatch.setattr(cmd.lifecycle, "provision_company", provision)
    monkeypatch.setattr(cmd, "call_command", record)
    # Членства своим сотрудникам читают hr в схеме компании; схем здесь нет.
    monkeypatch.setattr(cmd, "_own_staff_user_ids", lambda slug: [])
    monkeypatch.setattr(cmd, "serving_holders", lambda slug: [])
    return calls


def _run(**kwargs):
    call_command("seed_group_demo", verbosity=0, **kwargs)


@pytest.mark.django_db
def test_creates_the_four_companies_of_the_document(fake_provisioning):
    _run()
    rows = {c.slug: c for c in Company.objects.select_related("parent")}
    assert set(rows) == {"hi-tech-group", "hi-tech-qazaqstan", "hi-tech-systems",
                         "kazakhstan-engineering-group"}
    assert rows["hi-tech-group"].kind == "holding" and rows["hi-tech-group"].parent is None
    for slug in ("hi-tech-qazaqstan", "hi-tech-systems", "kazakhstan-engineering-group"):
        assert rows[slug].parent_id == rows["hi-tech-group"].id
    assert rows["hi-tech-qazaqstan"].kind == "construction"
    assert rows["hi-tech-systems"].kind == "it"
    assert rows["kazakhstan-engineering-group"].kind == "service"


@pytest.mark.django_db
def test_seeds_every_company_in_order_and_tasks_for_htq_only(fake_provisioning):
    _run()
    names = [(name, kw.get("company")) for name, kw in fake_provisioning]
    slugs = [s for s, *_ in cmd.GROUP]
    expected = []
    for slug in slugs:
        expected += [("seed_hr_demo", slug), ("seed_employee_accounts", slug)]
    expected.append(("seed_tasks_demo", "hi-tech-qazaqstan"))
    assert names == expected


@pytest.mark.django_db
def test_skip_tasks(fake_provisioning):
    _run(skip_tasks=True)
    assert all(name != "seed_tasks_demo" for name, _ in fake_provisioning)


@pytest.mark.django_db
def test_existing_company_is_kept_and_gets_its_parent(fake_provisioning):
    """dev-база после tenancy_bootstrap: HTQ уже есть, без родителя."""
    Company.objects.create(slug="hi-tech-qazaqstan", name="Hi-Tech Qazaqstan",
                           kind="construction")
    _run()
    htq = Company.objects.select_related("parent").get(slug="hi-tech-qazaqstan")
    assert htq.parent.slug == "hi-tech-group"
    assert Company.objects.count() == 4


@pytest.mark.django_db
def test_archived_company_in_the_group_is_refused(fake_provisioning):
    Company.objects.create(slug="hi-tech-systems", name="X", kind="it", status="archived")
    with pytest.raises(CommandError, match="архив"):
        _run()


@pytest.mark.django_db
def test_grants_membership_to_own_staff_and_serving_holders(fake_provisioning, monkeypatch):
    monkeypatch.setattr(cmd, "_own_staff_user_ids",
                        lambda slug: {"hi-tech-group": [11, 12], "hi-tech-systems": [31]}.get(slug, []))
    monkeypatch.setattr(cmd, "serving_holders",
                        lambda slug: [11] if slug != "hi-tech-group" else [])
    _run(skip_tasks=True)
    by = {(m.company.slug, m.user_id) for m in CompanyMembership.objects.select_related("company")}
    assert ("hi-tech-group", 11) in by and ("hi-tech-group", 12) in by
    assert ("hi-tech-systems", 31) in by
    # Обслуживающий холдинга — член каждого ДО (блок C, решение 6).
    for slug in ("hi-tech-qazaqstan", "hi-tech-systems", "kazakhstan-engineering-group"):
        assert (slug, 11) in by


@pytest.mark.django_db
def test_is_idempotent(fake_provisioning):
    _run(skip_tasks=True)
    _run(skip_tasks=True)
    assert Company.objects.count() == 4


@pytest.mark.django_db
def test_explains_why_there_are_no_serving_holders(fake_provisioning, capsys):
    """Ноль обслуживающих — штатное состояние свежего стенда (ролей ещё нет),
    и оно обязано быть объяснено: молчание здесь читается как «наследование
    прав сломано»."""
    _run(skip_tasks=True)
    out = capsys.readouterr().out
    assert "не назначены роли" in out
    assert "company_grant" in out


@pytest.mark.parametrize("host", ["10.0.0.5", "db.example.com", "203.0.113.10"])
def test_refuses_to_run_against_a_remote_database(host):
    with pytest.raises(CommandError, match="не похож на локальную"):
        cmd.Command()._assert_local(False, host=host)
