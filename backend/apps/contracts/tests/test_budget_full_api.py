"""``POST /budgets/full`` — составная заявка на бюджет.

Проверяется главное свойство маршрута: одна заявка заводит ОДИН бюджет с
НЕСКОЛЬКИМИ строками (по одной на программу, у каждой своя сумма) вместе с
недостающими справочниками — и делает это «всё или ничего». Полубюджета, в
котором часть программ профинансирована, а часть нет, существовать не
должно.
"""

from decimal import Decimal

import pytest
from django.test import Client

from apps.contracts.models import Administrator, Budget, BudgetLine, Country, Program

from .helpers import (
    BASE,
    auth,
    make_administrator,
    make_line,
    make_program,
    post_json,
    token,
)

pytestmark = pytest.mark.django_db


def payload(**over) -> dict:
    body = {
        "administrator": {
            "project_name": "Проект А",
            "country": {"name": "Казахстан", "iso_code": "KZ"},
        },
        "programs": [
            {"program": {"name": "Образование", "expense_item": "Оборудование",
                         "code": "EDU-01"},
             "amount": "5000000.00", "note": "закуп в Q1"},
            {"program": {"name": "Медицина", "expense_item": "Расходники"},
             "amount": "2300000.00", "note": ""},
        ],
        "period_year": 2026,
        "currency": "KZT",
    }
    body.update(over)
    return body


def test_creates_one_budget_with_a_line_per_program():
    client = Client()
    response = post_json(client, f"{BASE}/budgets/full", payload(), **auth(token()))

    assert response.status_code == 201
    body = response.json()

    # Год, валюта и администратор — на самом бюджете, по разу.
    assert body["period_year"] == 2026
    assert body["currency"] == "KZT"
    # «Выделено» — сумма строк, хранимой колонки под неё нет.
    assert Decimal(body["allocated"]) == Decimal("7300000.00")

    # Суммы и примечания принадлежат СТРОКАМ: они разные.
    lines = body["lines"]
    assert len(lines) == 2
    assert [row["amount"] for row in lines] == ["5000000.00", "2300000.00"]
    assert [row["note"] for row in lines] == ["закуп в Q1", ""]

    assert Budget.objects.count() == 1
    assert BudgetLine.objects.count() == 2
    assert Program.objects.count() == 2
    assert Administrator.objects.count() == 1
    assert Country.objects.count() == 1


def test_existing_references_are_reused_not_duplicated():
    administrator = make_administrator()
    program = make_program(name="Образование", expense_item="Оборудование")
    client = Client()

    response = post_json(client, f"{BASE}/budgets/full", payload(
        administrator={"id": administrator.pk},
        programs=[
            {"program": {"id": program.pk}, "amount": "100.00", "note": ""},
            {"program": {"name": "Медицина", "expense_item": "Расходники"},
             "amount": "200.00", "note": ""},
        ],
    ), **auth(token()))

    assert response.status_code == 201
    assert Administrator.objects.count() == 1
    # Одна старая программа + одна заведённая заявкой.
    assert Program.objects.count() == 2
    assert Budget.objects.count() == 1


def test_a_second_budget_for_the_same_year_is_rejected():
    """У проекта один бюджет на год и валюту.

    Второй контейнер сделал бы вопрос «сколько выделено проекту на 2026-й»
    неоднозначным, поэтому заявка отбивается целиком: ни строк, ни
    заведённых по пути справочников после отказа остаться не должно.
    """
    taken = make_line(period_year=2026)
    client = Client()

    response = post_json(client, f"{BASE}/budgets/full", payload(
        administrator={"id": taken.budget.administrator_id},
        programs=[
            {"program": {"name": "Медицина", "expense_item": "Расходники"},
             "amount": "200.00", "note": ""},
        ],
    ), **auth(token()))

    assert response.status_code == 409
    assert Budget.objects.count() == 1          # только тот, что был до заявки
    assert Budget.objects.first().pk == taken.budget_id
    assert not Program.objects.filter(name="Медицина").exists()


def test_a_conflicting_line_rolls_back_the_whole_budget():
    """Если падает одна строка, не остаётся ни бюджета, ни соседних строк.

    Иначе повторная отправка формы натыкалась бы уже на собственный мусор:
    бюджет-то создан, а программ в нём половина.
    """
    existing = make_program(name="Медицина", expense_item="Расходники")
    client = Client()

    response = post_json(client, f"{BASE}/budgets/full", payload(programs=[
        {"program": {"name": "Образование", "expense_item": "Оборудование"},
         "amount": "200.00", "note": ""},
        {"program": {"id": existing.pk}, "amount": "300.00", "note": ""},
        # Та же программа, что и предыдущая строка, но записанная НЕ через
        # id: для схемы это разные ключи, и дубль она пропускает —
        # `_resolve_program` схлопнет обе в одну запись, и поймает его уже
        # уникальный индекс (budget, program).
        {"program": {"name": "Медицина", "expense_item": "Расходники"},
         "amount": "400.00", "note": ""},
    ]), **auth(token()))

    assert response.status_code == 409
    assert "Медицина" in response.json()["detail"]
    # Ни бюджета, ни успевшей пройти первой строки.
    assert Budget.objects.count() == 0
    assert BudgetLine.objects.count() == 0
    # Программа, заведённая по пути, тоже откатилась; та, что была до
    # заявки, — цела.
    assert not Program.objects.filter(name="Образование").exists()
    assert Program.objects.filter(pk=existing.pk).exists()


def test_same_program_twice_is_rejected_as_schema_error():
    """Дубль внутри заявки ловится схемой (422), а не уникальным индексом.

    409 «бюджет уже существует» здесь врал бы: бюджета нет, проблема в самой
    форме.
    """
    program = make_program()
    client = Client()

    response = post_json(client, f"{BASE}/budgets/full", payload(
        administrator={"id": make_administrator(project_name="Проект Б").pk},
        programs=[
            {"program": {"id": program.pk}, "amount": "100.00", "note": ""},
            {"program": {"id": program.pk}, "amount": "200.00", "note": ""},
        ],
    ), **auth(token()))

    assert response.status_code == 422
    assert Budget.objects.count() == 0


def test_empty_program_list_is_rejected():
    client = Client()
    response = post_json(client, f"{BASE}/budgets/full", payload(programs=[]),
                         **auth(token()))

    assert response.status_code == 422
    assert Budget.objects.count() == 0


def test_amount_wider_than_the_column_is_a_schema_error_not_a_crash():
    """19-значная сумма не должна доходить до Postgres.

    ``numeric field overflow`` — это ``DataError``, его не ловит
    ``conflict_as``, и заполняющий получил бы 500 вместо внятного отказа.
    """
    client = Client()
    response = post_json(client, f"{BASE}/budgets/full", payload(programs=[
        {"program": {"name": "Образование", "expense_item": "Оборудование"},
         "amount": "1" + "0" * 18, "note": ""},
    ]), **auth(token()))

    assert response.status_code == 422
    assert Budget.objects.count() == 0


def test_single_program_application_still_works():
    """Заявка на одну программу — не особый случай, тот же список из одного."""
    client = Client()
    response = post_json(client, f"{BASE}/budgets/full", payload(programs=[
        {"program": {"name": "Образование", "expense_item": "Оборудование"},
         "amount": "999.99", "note": ""},
    ]), **auth(token()))

    assert response.status_code == 201
    assert len(response.json()["lines"]) == 1
    assert BudgetLine.objects.get().amount == Decimal("999.99")
