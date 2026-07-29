"""Справочники: страны, программы, администраторы, бюджеты, контрагенты.

Главное, что здесь проверяется помимо CRUD, — что ``PROTECT`` и уникальные
ограничения доходят до клиента как 409 с внятным текстом, а не как 500 из
глубины ORM.
"""

from decimal import Decimal

import pytest
from django.test import Client

from apps.contracts.models import AgreementStatus, Budget, Counterparty, Program

from .helpers import (
    BASE,
    admin_token,
    auth,
    make_administrator,
    make_agreement,
    make_budget,
    make_counterparty,
    make_country,
    make_program,
    patch_json,
    post_json,
    token,
)


# ── Программы ────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_program_crud():
    client = Client()
    created = post_json(client, f"{BASE}/programs",
                        {"name": "Образование", "expense_item": "Оборудование"},
                        **auth(admin_token()))
    assert created.status_code == 201, created.content
    program_id = created.json()["id"]

    # Без кода подпись — просто название: код необязателен, и ведущий
    # пробел в «код название» появиться не должен.
    assert created.json()["display_name"] == "Образование"

    patched = patch_json(client, f"{BASE}/programs/{program_id}",
                         {"code": "EDU-01"}, **auth(admin_token()))
    assert patched.json()["code"] == "EDU-01"
    assert patched.json()["display_name"] == "EDU-01 Образование"

    assert client.delete(f"{BASE}/programs/{program_id}",
                         **auth(admin_token())).status_code == 204
    assert Program.objects.count() == 0


@pytest.mark.django_db
def test_budget_card_labels_the_program_with_its_code():
    """`program_name` в карточке бюджета — подпись «код название», а не
    голое имя: код заказчик ведёт как основной идентификатор программы."""
    budget = make_budget(program=make_program(name="Образование", code="EDU-01"))

    resp = Client().get(f"{BASE}/budgets/{budget.pk}", **auth(token()))
    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert body["program_name"] == "EDU-01 Образование"
    # Статья расходов в подпись не входит — она отдельным полем.
    assert body["expense_item"] == budget.program.expense_item


@pytest.mark.django_db
def test_duplicate_program_is_409():
    make_program(name="Образование", expense_item="Оборудование")
    resp = post_json(Client(), f"{BASE}/programs",
                     {"name": "Образование", "expense_item": "Оборудование"},
                     **auth(admin_token()))
    assert resp.status_code == 409, resp.content


@pytest.mark.django_db
def test_program_in_use_cannot_be_deleted():
    budget = make_budget()
    resp = Client().delete(f"{BASE}/programs/{budget.program_id}", **auth(admin_token()))
    assert resp.status_code == 409
    assert "is_active" in resp.json()["detail"]


# ── Администраторы ───────────────────────────────────────────────────────

@pytest.mark.django_db
def test_administrator_create_rejects_unknown_country_with_404():
    resp = post_json(Client(), f"{BASE}/administrators",
                     {"country_id": 9999, "project_name": "Проект А"},
                     **auth(admin_token()))
    assert resp.status_code == 404, resp.content


# ── Бюджеты ──────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_budget_create_and_read_exposes_computed_fields():
    administrator = make_administrator()
    program = make_program()
    resp = post_json(Client(), f"{BASE}/budgets",
                     {"administrator_id": administrator.pk, "program_id": program.pk,
                      "amount": "5000000.00", "period_year": 2026},
                     **auth(admin_token()))
    assert resp.status_code == 201, resp.content
    body = resp.json()
    assert Decimal(body["committed"]) == Decimal("0.00")
    assert Decimal(body["remaining"]) == Decimal("5000000.00")
    assert body["expense_item"] == program.expense_item


@pytest.mark.django_db
def test_duplicate_budget_line_is_409():
    budget = make_budget()
    resp = post_json(Client(), f"{BASE}/budgets",
                     {"administrator_id": budget.administrator_id,
                      "program_id": budget.program_id,
                      "amount": "1.00", "period_year": budget.period_year},
                     **auth(admin_token()))
    assert resp.status_code == 409, resp.content


@pytest.mark.django_db
def test_budget_cannot_shrink_below_committed():
    budget = make_budget(amount="1000000.00")
    make_agreement(budget=budget, amount="700000.00", status=AgreementStatus.SIGNED)

    resp = patch_json(Client(), f"{BASE}/budgets/{budget.pk}",
                      {"amount": "500000.00"}, **auth(admin_token()))
    assert resp.status_code == 409, resp.content
    budget.refresh_from_db()
    assert budget.amount == Decimal("1000000.00")


@pytest.mark.django_db
def test_budget_with_agreements_cannot_be_deleted():
    budget = make_budget()
    make_agreement(budget=budget, amount="1000.00", status=AgreementStatus.SIGNED)

    resp = Client().delete(f"{BASE}/budgets/{budget.pk}", **auth(admin_token()))
    assert resp.status_code == 409
    assert Budget.objects.filter(pk=budget.pk).exists()


@pytest.mark.django_db
def test_budget_agreements_subresource_404s_for_unknown_budget():
    assert Client().get(f"{BASE}/budgets/9999/agreements",
                        **auth(token())).status_code == 404


@pytest.mark.django_db
def test_budget_list_filters_by_administrator():
    country = make_country(name="Казахстан")
    first = make_budget(administrator=make_administrator(country=country,
                                                        project_name="Проект А"))
    make_budget(administrator=make_administrator(country=country, project_name="Проект Б"),
                program=first.program)

    resp = Client().get(f"{BASE}/budgets?administrator_id={first.administrator_id}",
                        **auth(token()))
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    # Подпись администратора после снятия ФИО — «проект страна».
    assert body[0]["administrator_name"] == "Проект А Казахстан"


# ── Контрагенты ──────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_counterparty_crud_and_search():
    country = make_country()
    client = Client()
    created = post_json(client, f"{BASE}/counterparties",
                        {"bin_iin": "123456789012", "name": "ТОО «Альфа»",
                         "country_id": country.pk, "vat": True,
                         "address": "Алматы", "contacts": "+7 700 000 00 00"},
                        **auth(admin_token()))
    assert created.status_code == 201, created.content
    assert created.json()["vat"] is True
    assert created.json()["vat_label"] == "с НДС"

    by_name = client.get(f"{BASE}/counterparties?search=Альфа", **auth(token()))
    assert len(by_name.json()) == 1
    by_bin = client.get(f"{BASE}/counterparties?search=1234", **auth(token()))
    assert len(by_bin.json()) == 1


@pytest.mark.django_db
def test_counterparty_vat_defaults_to_false_and_is_togglable():
    """НДС — признак «с / без», а не текст: он необязателен в теле запроса,
    по умолчанию False, и PATCH'ем переключается в обе стороны (False здесь
    значит «снять», а не «поле не пришло» — ср. соглашение по PATCH-схемам)."""
    country = make_country()
    client = Client()
    created = post_json(client, f"{BASE}/counterparties",
                        {"bin_iin": "987654321098", "name": "ИП Бета",
                         "country_id": country.pk},
                        **auth(admin_token()))
    assert created.status_code == 201, created.content
    assert created.json()["vat"] is False
    assert created.json()["vat_label"] == "без НДС"

    on = patch_json(client, f"{BASE}/counterparties/{created.json()['id']}",
                    {"vat": True}, **auth(admin_token()))
    assert on.json()["vat"] is True

    off = patch_json(client, f"{BASE}/counterparties/{created.json()['id']}",
                     {"vat": False}, **auth(admin_token()))
    assert off.json()["vat"] is False
    assert off.json()["vat_label"] == "без НДС"


@pytest.mark.django_db
def test_duplicate_bin_iin_is_409():
    country = make_country()
    make_counterparty(country=country, bin_iin="123456789012")
    resp = post_json(Client(), f"{BASE}/counterparties",
                     {"bin_iin": "123456789012", "name": "Другое ТОО",
                      "country_id": country.pk},
                     **auth(admin_token()))
    assert resp.status_code == 409, resp.content


@pytest.mark.django_db
def test_counterparty_with_agreements_cannot_be_deleted():
    budget = make_budget()
    agreement = make_agreement(budget=budget, amount="1000.00",
                               status=AgreementStatus.SIGNED)

    resp = Client().delete(f"{BASE}/counterparties/{agreement.counterparty_id}",
                           **auth(admin_token()))
    assert resp.status_code == 409
    assert Counterparty.objects.filter(pk=agreement.counterparty_id).exists()


# ── Служебное ────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_enums_endpoint_reports_the_committing_statuses():
    """Фронтенду нужно знать, из каких статусов договор занимает бюджет —
    иначе он не сможет объяснить, почему сохранение черновика не изменило
    остаток."""
    resp = Client().get(f"{BASE}/enums", **auth(token()))
    assert resp.status_code == 200
    body = resp.json()
    assert body["committing_statuses"] == ["approved", "executed", "on_review", "signed"]
    assert body["transitions"]["executed"] == []
    assert {row["value"] for row in body["payment_type"]} == {
        "prepayment", "postpayment", "staged"}
