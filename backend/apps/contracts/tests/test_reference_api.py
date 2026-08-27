"""Справочники: страны, программы, администраторы, бюджеты, контрагенты.

Главное, что здесь проверяется помимо CRUD, — что ``PROTECT`` и уникальные
ограничения доходят до клиента как 409 с внятным текстом, а не как 500 из
глубины ORM.
"""

from decimal import Decimal

import pytest
from django.test import Client

from apps.contracts.models import (
    AgreementStatus,
    Budget,
    BudgetLine,
    Counterparty,
    Program,
)

from .helpers import (
    BASE,
    admin_token,
    auth,
    make_administrator,
    make_agreement,
    make_budget,
    make_line,
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
    """`program_name` в строке бюджета — подпись «код название», а не голое
    имя: код заказчик ведёт как основной идентификатор программы."""
    line = make_line(program=make_program(name="Образование", code="EDU-01"))

    resp = Client().get(f"{BASE}/budgets/{line.budget_id}", **auth(token()))
    assert resp.status_code == 200, resp.content
    row = resp.json()["lines"][0]
    assert row["program_name"] == "EDU-01 Образование"
    # Статья расходов в подпись не входит — она отдельным полем.
    assert row["expense_item"] == line.program.expense_item


@pytest.mark.django_db
def test_duplicate_program_is_409():
    make_program(name="Образование", expense_item="Оборудование")
    resp = post_json(Client(), f"{BASE}/programs",
                     {"name": "Образование", "expense_item": "Оборудование"},
                     **auth(admin_token()))
    assert resp.status_code == 409, resp.content


@pytest.mark.django_db
def test_program_in_use_cannot_be_deleted():
    line = make_line()
    resp = Client().delete(f"{BASE}/programs/{line.program_id}", **auth(admin_token()))
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
def test_budget_card_totals_its_lines():
    """«Выделено» у бюджета — сумма строк, а не хранимая колонка."""
    line = make_line(amount="5000000.00")
    make_line(budget=line.budget, program=make_program(name="Медицина"),
              amount="2000000.00")

    resp = Client().get(f"{BASE}/budgets/{line.budget_id}", **auth(token()))
    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert Decimal(body["allocated"]) == Decimal("7000000.00")
    assert Decimal(body["committed"]) == Decimal("0.00")
    assert Decimal(body["remaining"]) == Decimal("7000000.00")
    assert len(body["lines"]) == 2


@pytest.mark.django_db
def test_adding_a_program_twice_to_one_budget_is_409():
    line = make_line()
    resp = post_json(Client(), f"{BASE}/budgets/{line.budget_id}/lines",
                     {"program_id": line.program_id, "amount": "1.00"},
                     **auth(admin_token()))
    assert resp.status_code == 409, resp.content


@pytest.mark.django_db
def test_adding_a_program_to_an_existing_budget_updates_the_total():
    """Дополнить уже заведённый бюджет новой программой — отдельная
    операция: переотправлять ради этого всю форму значило бы рисковать
    затереть чужие правки соседних строк."""
    line = make_line(amount="1000000.00")
    program = make_program(name="Медицина", expense_item="Расходники")

    resp = post_json(Client(), f"{BASE}/budgets/{line.budget_id}/lines",
                     {"program_id": program.pk, "amount": "500000.00"},
                     **auth(admin_token()))
    assert resp.status_code == 201, resp.content
    body = resp.json()
    assert Decimal(body["allocated"]) == Decimal("1500000.00")
    assert len(body["lines"]) == 2


@pytest.mark.django_db
def test_budget_line_cannot_shrink_below_committed():
    line = make_line(amount="1000000.00")
    make_agreement(line=line, amount="700000.00", status=AgreementStatus.SIGNED)

    resp = patch_json(Client(), f"{BASE}/budget-lines/{line.pk}",
                      {"amount": "500000.00"}, **auth(admin_token()))
    assert resp.status_code == 409, resp.content
    line.refresh_from_db()
    assert line.amount == Decimal("1000000.00")


@pytest.mark.django_db
def test_budget_with_agreements_cannot_be_deleted():
    """Строки уходят каскадом, но строка с договором держится PROTECT'ом —
    бюджет остаётся цел."""
    line = make_line()
    make_agreement(line=line, amount="1000.00", status=AgreementStatus.SIGNED)

    resp = Client().delete(f"{BASE}/budgets/{line.budget_id}", **auth(admin_token()))
    assert resp.status_code == 409
    assert Budget.objects.filter(pk=line.budget_id).exists()
    assert BudgetLine.objects.filter(pk=line.pk).exists()


@pytest.mark.django_db
def test_budget_agreements_subresource_404s_for_unknown_budget():
    assert Client().get(f"{BASE}/budgets/9999/agreements",
                        **auth(token())).status_code == 404


@pytest.mark.django_db
def test_budget_list_filters_by_administrator():
    country = make_country(name="Казахстан")
    first = make_line(administrator=make_administrator(country=country,
                                                       project_name="Проект А"))
    make_line(administrator=make_administrator(country=country,
                                               project_name="Проект Б"),
              program=first.program)

    resp = Client().get(
        f"{BASE}/budgets?administrator_id={first.budget.administrator_id}",
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
                         "address": "Алматы", "contact_name": "Петров П.",
                         "phone": "+7 700 000 00 00", "email": "info@alfa.kz"},
                        **auth(admin_token()))
    assert created.status_code == 201, created.content
    assert created.json()["vat"] is True
    assert created.json()["vat_label"] == "с НДС"
    assert created.json()["phone"] == "+7 700 000 00 00"
    assert created.json()["email"] == "info@alfa.kz"

    by_name = client.get(f"{BASE}/counterparties?search=Альфа", **auth(token()))
    assert len(by_name.json()) == 1
    by_bin = client.get(f"{BASE}/counterparties?search=1234", **auth(token()))
    assert len(by_bin.json()) == 1


@pytest.mark.django_db
def test_counterparty_list_can_return_a_searchable_page():
    country = make_country()
    make_counterparty(country=country, bin_iin="100000000001", name="ТОО Альфа")
    make_counterparty(country=country, bin_iin="100000000002", name="ТОО Бета")
    make_counterparty(country=country, bin_iin="100000000003", name="ТОО Гамма")

    response = Client().get(
        f"{BASE}/counterparties?page=2&page_size=1",
        **auth(token()),
    )

    assert response.status_code == 200, response.content
    body = response.json()
    assert body["pagination"] == {
        "page": 2,
        "page_size": 1,
        "total": 3,
        "total_pages": 3,
    }
    assert len(body["items"]) == 1

    searched = Client().get(
        f"{BASE}/counterparties?page=1&page_size=25&search=Бета",
        **auth(token()),
    )
    assert searched.json()["pagination"]["total"] == 1
    assert searched.json()["items"][0]["name"] == "ТОО Бета"


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
def test_counterparty_contacts_are_three_fields_with_a_ready_summary():
    """Контакты разложены по полям, а склейку для списков даёт бэкенд.

    Пустой контакт — это пустая строка во всех трёх полях: карточку заводят
    и по одному БИН'у, контакты дописывают позже.
    """
    country = make_country()
    client = Client()
    created = post_json(client, f"{BASE}/counterparties",
                        {"bin_iin": "111111111111", "name": "ТОО «Гамма»",
                         "country_id": country.pk},
                        **auth(admin_token()))
    assert created.status_code == 201, created.content
    body = created.json()
    assert (body["contact_name"], body["phone"], body["email"],
            body["contact_summary"]) == ("", "", "", "")

    filled = patch_json(client, f"{BASE}/counterparties/{body['id']}",
                        {"contact_name": "Петров П.",
                         "phone": "+7 700 000 00 00", "email": "info@gamma.kz"},
                        **auth(admin_token()))
    assert filled.status_code == 200, filled.content
    assert filled.json()["contact_summary"] == (
        "Петров П., +7 700 000 00 00, info@gamma.kz")


@pytest.mark.django_db
def test_counterparty_email_must_look_like_an_email():
    """Ради этого поле и вынули из свободной строки: мусор не проходит,
    а пустое значение остаётся законным."""
    country = make_country()
    resp = post_json(Client(), f"{BASE}/counterparties",
                     {"bin_iin": "222222222222", "name": "ТОО «Дельта»",
                      "country_id": country.pk, "email": "директор, звонить днём"},
                     **auth(admin_token()))
    assert resp.status_code == 422, resp.content


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
    line = make_line()
    agreement = make_agreement(line=line, amount="1000.00",
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
