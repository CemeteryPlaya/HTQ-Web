"""Жизненный цикл компании — сервис, общий для CLI и HTTP.

Проверяются только правила, которых не было в командах: гейт последней
действующей компании (roadmap §3, п.4), правка с проверкой цикла в дереве
владения, отказы без побочных эффектов. Заведение со схемой и откаты
по-прежнему покрывает test_company_create.py — команда стала обёрткой.
"""

import pytest
from django.core.management import CommandError, call_command

from apps.companies.models import Company, CompanyKind, CompanyStatus
from apps.companies.services import lifecycle, schema_service


@pytest.mark.django_db(transaction=True)
def test_archive_refuses_the_last_active_company(company_schema):
    with pytest.raises(lifecycle.LastActiveCompany) as exc:
        lifecycle.archive_company(company_schema["slug"])
    assert exc.value.status == 409
    assert exc.value.code == "last_active"
    assert Company.objects.get(slug=company_schema["slug"]).status == CompanyStatus.ACTIVE


@pytest.mark.django_db(transaction=True)
def test_cli_archive_refuses_the_last_active_company(company_schema):
    with pytest.raises(CommandError, match="единственная действующая"):
        call_command("company_archive", "--company", company_schema["slug"])


@pytest.mark.django_db
def test_archive_unknown_company_is_404():
    with pytest.raises(lifecycle.CompanyNotFound) as exc:
        lifecycle.archive_company("net-takoy")
    assert exc.value.status == 404


@pytest.mark.django_db
def test_update_changes_name_kind_country_and_parent():
    holding = Company.objects.create(slug="grp", name="Group", kind=CompanyKind.HOLDING)
    Company.objects.create(slug="htq", name="HTQ", kind=CompanyKind.REGIONAL)

    updated = lifecycle.update_company(
        "htq", name="Hi-Tech Qazaqstan", kind="construction", country="KZ",
        parent_slug="grp",
    )
    assert updated.name == "Hi-Tech Qazaqstan"
    assert updated.kind == CompanyKind.CONSTRUCTION
    assert updated.country == "KZ"
    assert updated.parent_id == holding.id


@pytest.mark.django_db
def test_update_without_parent_key_keeps_parent_and_with_null_clears_it():
    holding = Company.objects.create(slug="grp", name="Group", kind=CompanyKind.HOLDING)
    Company.objects.create(slug="htq", name="HTQ", kind=CompanyKind.CONSTRUCTION, parent=holding)

    assert lifecycle.update_company("htq", name="HTQ-2").parent_id == holding.id
    assert lifecycle.update_company("htq", parent_slug=None).parent_id is None


@pytest.mark.django_db
def test_update_rejects_self_and_cycle_as_parent():
    a = Company.objects.create(slug="a", name="A", kind=CompanyKind.HOLDING)
    Company.objects.create(slug="b", name="B", kind=CompanyKind.SERVICE, parent=a)

    with pytest.raises(lifecycle.ParentCycle):
        lifecycle.update_company("a", parent_slug="a")
    with pytest.raises(lifecycle.ParentCycle):
        lifecycle.update_company("a", parent_slug="b")
    assert Company.objects.get(slug="a").parent_id is None


@pytest.mark.django_db
def test_update_rejects_unknown_parent_and_kind():
    Company.objects.create(slug="a", name="A", kind=CompanyKind.HOLDING)
    with pytest.raises(lifecycle.ParentNotFound):
        lifecycle.update_company("a", parent_slug="nope")
    with pytest.raises(lifecycle.CompanyInvalid):
        lifecycle.update_company("a", kind="branch")


@pytest.mark.django_db(transaction=True)
def test_provision_rejects_duplicate_before_touching_the_schema(company_schema):
    with pytest.raises(lifecycle.CompanyExists):
        lifecycle.provision_company(slug=company_schema["slug"], name="Дубль", kind="service")
    # Схема фикстуры на месте, лишней не появилось.
    assert schema_service.schema_exists(company_schema["slug"])
