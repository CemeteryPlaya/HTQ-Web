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
def test_force_remote_is_propagated_to_every_subordinate_seed(fake_provisioning):
    """Без прокидывания флага команда на неместной БД успела бы завести
    четыре компании, четыре схемы, прогнать миграции и пересобрать сводки
    холдинга — и только потом упасть на страже ``seed_hr_demo``. Все три
    вызываемых сида обязаны получить тот же ``--force-remote``."""
    _run(force_remote=True)
    assert fake_provisioning  # хотя бы один call_command реально записан
    for name, kwargs in fake_provisioning:
        assert kwargs.get("force_remote") is True, name


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
def test_existing_company_gets_parent_and_kind_warning_independently(fake_provisioning, capsys):
    """Обе проверки в ``_ensure_company`` обязаны отработать независимо:
    раньше ветка выставления родителя делала ``return`` и проглатывала
    предупреждение о виде — компания с неверным видом И без родителя
    предупреждения не получала вовсе."""
    Company.objects.create(slug="hi-tech-systems", name="Hi-Tech Systems", kind="construction")
    _run()
    out = capsys.readouterr().out
    hts = Company.objects.select_related("parent").get(slug="hi-tech-systems")
    assert hts.parent.slug == "hi-tech-group"
    assert "родитель выставлен" in out
    assert "не меняю" in out


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
def test_is_idempotent(fake_provisioning, monkeypatch):
    """Второй прогон не должен ни падать, ни заводить новые членства —
    ``granted_serving``/``total_holders`` из первого прогона не может расти
    молча на неизменном входе."""
    monkeypatch.setattr(cmd, "_own_staff_user_ids",
                        lambda slug: {"hi-tech-group": [11]}.get(slug, []))

    _run(skip_tasks=True)
    assert Company.objects.count() == 4
    memberships_after_first = CompanyMembership.objects.count()
    assert memberships_after_first > 0

    _run(skip_tasks=True)

    assert Company.objects.count() == 4
    assert CompanyMembership.objects.count() == memberships_after_first


@pytest.mark.django_db
def test_explains_why_there_are_no_serving_holders(fake_provisioning, capsys):
    """Ноль обслуживающих — штатное состояние свежего стенда (ролей ещё нет),
    и оно обязано быть объяснено: молчание здесь читается как «наследование
    прав сломано»."""
    _run(skip_tasks=True)
    out = capsys.readouterr().out
    assert "не назначены роли" in out
    assert "company_grant" in out


@pytest.mark.django_db
def test_explanation_disappears_once_serving_holders_actually_have_membership(
    fake_provisioning, monkeypatch, capsys,
):
    """Вырожденность ``test_explains_why_there_are_no_serving_holders``:
    фикстура подменяет ``serving_holders`` пустым списком, и там «держателей
    ноль» и «новых членств ноль» истинны одновременно — тест физически не
    может отличить правильный гейт от неправильного (гейт по числу НОВЫХ
    грантов лжёт на третьем прогоне: держатели есть, новых грантов уже нет).

    Здесь держатели ЕСТЬ с первого прогона; после того как второй прогон
    выдал им членство, объяснение обязано пропасть, а не повторяться на
    пустом месте, отправляя оператора переделывать уже сделанное.
    """
    monkeypatch.setattr(cmd, "serving_holders",
                        lambda slug: [11] if slug != "hi-tech-group" else [])

    _run(skip_tasks=True)
    capsys.readouterr()  # первый прогон: держатель ещё без членства — не проверяем здесь
    _run(skip_tasks=True)

    out = capsys.readouterr().out
    assert "не назначены роли" not in out


@pytest.mark.django_db
def test_guard_runs_before_anything_is_written(monkeypatch):
    """Отказ обязан случиться ДО заведения первой компании: эта команда
    заводит СХЕМЫ Postgres, и «половина стенда на чужом хосте» здесь дороже,
    чем у ``seed_hr_demo`` (тот же приём —
    ``apps/hr/tests/test_seed_hr_demo.py::test_guard_runs_before_anything_is_written``)."""
    def refuse(self, force, host=None):
        raise CommandError("DB_HOST не похож на локальную БД")

    monkeypatch.setattr(cmd.Command, "_assert_local", refuse)

    with pytest.raises(CommandError, match="не похож на локальную"):
        _run()

    assert Company.objects.count() == 0


@pytest.mark.parametrize("host", ["10.0.0.5", "db.example.com", "203.0.113.10"])
def test_refuses_to_run_against_a_remote_database(host):
    with pytest.raises(CommandError, match="не похож на локальную"):
        cmd.Command()._assert_local(False, host=host)
