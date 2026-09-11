# -*- coding: utf-8 -*-
"""Сквозной прогон по реальной карточке договора — HTQ 04/2026, QAZAQSTAN-Aralsk.

Отдельный файл, а не ещё пара тестов в ``test_agreements_api.py``: там каждый
тест проверяет ОДНО правило на минимальном договоре, а здесь важно обратное —
что все реквизиты карточки едут вместе и не мешают друг другу. Данные взяты из
настоящей карточки, включая её особенности:

* направление «Поступление» — лимит строки бюджета такому договору не писан;
* ставка НДС 0,1 %, а не 12 % — редкий, но допустимый случай;
* срок исполнения задан СЛОВОМ «уточнить», даты нет вовсе;
* суммы в карточке НЕ СВОДЯТСЯ (99 999 999 999 + 99 999 999 ≠ 99 999 999).
  Бэкенд их не сверяет и принимает как есть — это зафиксировано тестом
  ``test_totals_in_the_card_do_not_add_up_and_nothing_objects``, чтобы
  поведение было решением, а не случайностью.
"""
from decimal import Decimal

import pytest
from django.test import Client

from apps.contracts.models import Agreement, AgreementStatus, Budget, BudgetLine
from .helpers import (BASE, admin_token, auth, make_administrator, make_budget,
                      make_counterparty, make_country, make_program, post_json,
                      token)

# Ровно как в карточке.
BEZ_NDS = "99999999999"      # Договор без НДС   99 999 999 999
NDS     = "99999999"         # Договор НДС           99 999 999
VSEGO   = "99999999"         # Договор всего         99 999 999


@pytest.fixture
def scenario(db):
    country = make_country()
    administrator = make_administrator(country=country, project_name="QAZAQSTAN-Aralsk")
    program = make_program(name="Ограждение/дороги/выравнивание",
                           expense_item="Ограждение/дороги/выравнивание",
                           code="3019")
    budget = make_budget(administrator=administrator, period_year=2026, currency="KZT")
    line = BudgetLine.objects.create(budget=budget, program=program,
                                     amount=Decimal("1000000000000.00"))
    counterparty = make_counterparty(country=country,
                                     name="ТОО «Снабкомплект Монтаж»",
                                     bin_iin="80340019927")
    return line, counterparty


def card_body(line, counterparty, **over):
    body = {
        "number": "HTQ 04/2026",
        "name": "Монтаж ограждения, дороги, выравнивание, земляные работы",
        "budget_line_id": line.pk,
        "counterparty_id": counterparty.pk,
        "direction": "income",              # Направление: Поступление
        "kind": "works_services",           # Вид: РиУ
        "contract_type": "standard",        # Тип: стандарт
        "sed_number": "DOC-00026-20260623", # № СЭД
        "subject": "Монтаж ограждения, дороги, выравнивание, земляные работы",
        "manager_name": "Куаныш Садиев",    # Менеджер
        "signed_date": "2026-05-28",        # Дата дог. 28.05.2026
        "start_date": "2026-05-28",         # Дата нач. 28.05.2026
        "term_comment": "уточнить",         # Срок исп. — текстом, даты нет
        "has_vat": True,                    # Флаг НДС: с
        "vat_rate": "0.10",                 # НДС 0,1 %
        "amount_without_vat": BEZ_NDS,
        "vat_amount": NDS,
        "amount": VSEGO,
        "has_advance": False,               # Аванс: нет
        "retention_rate": "5.00",           # Гар. уд. 5 %
        "payment_type": "postpayment",
        "currency": "KZT",
        "status": AgreementStatus.SIGNED.value,
    }
    body.update(over)
    return body


def test_card_is_saved_and_read_back_verbatim(scenario):
    """Каждое поле карточки доезжает до БД и возвращается тем же значением."""
    line, counterparty = scenario
    resp = post_json(Client(), f"{BASE}/agreements",
                     card_body(line, counterparty), **auth(admin_token()))
    assert resp.status_code == 201, resp.content
    d = resp.json()

    assert d["number"] == "HTQ 04/2026"
    assert d["direction"] == "income"
    assert d["kind"] == "works_services"
    assert d["contract_type"] == "standard"
    assert d["sed_number"] == "DOC-00026-20260623"
    assert d["subject"] == "Монтаж ограждения, дороги, выравнивание, земляные работы"
    assert d["manager_name"] == "Куаныш Садиев"
    assert d["counterparty_name"] == "ТОО «Снабкомплект Монтаж»"
    assert d["counterparty_bin_iin"] == "80340019927"
    assert d["signed_date"] == "2026-05-28"
    assert d["start_date"] == "2026-05-28"
    assert d["end_date"] is None          # срок задан текстом, не датой
    assert d["term_comment"] == "уточнить"
    assert d["has_vat"] is True
    assert Decimal(d["vat_rate"]) == Decimal("0.10")
    assert d["has_advance"] is False
    assert Decimal(d["retention_rate"]) == Decimal("5.00")
    assert Decimal(d["amount_without_vat"]) == Decimal(BEZ_NDS)
    assert Decimal(d["vat_amount"]) == Decimal(NDS)
    assert Decimal(d["amount"]) == Decimal(VSEGO)

    # Проект и статья бюджета — через строку бюджета.
    # display_name администратора — «проект страна».
    assert d["administrator_name"] == "QAZAQSTAN-Aralsk Казахстан"
    # Код статьи не отдельное поле: Program.display_name склеивает «код имя».
    assert d["program_name"] == "3019 Ограждение/дороги/выравнивание"
    assert d["expense_item"] == "Ограждение/дороги/выравнивание"

    row = Agreement.objects.get(pk=d["id"])
    assert row.amount_without_vat == Decimal(BEZ_NDS)
    assert row.direction == "income"


def test_income_card_leaves_the_expense_limit_untouched(scenario):
    """Поступление не занимает расходный лимит строки."""
    line, counterparty = scenario
    resp = post_json(Client(), f"{BASE}/agreements",
                     card_body(line, counterparty), **auth(admin_token()))
    assert resp.status_code == 201, resp.content

    detail = Client().get(f"{BASE}/budgets/{line.budget_id}", **auth(token()))
    assert detail.status_code == 200, detail.content
    row = [r for r in detail.json()["lines"] if r["id"] == line.pk][0]
    assert Decimal(row["committed"]) == Decimal("0.00"), row
    assert Decimal(row["remaining"]) == Decimal(row["amount"]), row


def test_the_same_card_as_an_expense_would_hit_the_limit(scenario):
    """Контроль: та же сумма расходом упирается в лимит строки."""
    line, counterparty = scenario
    line.amount = Decimal("50000000.00")     # меньше суммы договора
    line.save(update_fields=["amount"])
    resp = post_json(Client(), f"{BASE}/agreements",
                     card_body(line, counterparty, direction="expense"),
                     **auth(admin_token()))
    assert resp.status_code == 409, (resp.status_code, resp.content)

    # А поступлением — проходит, лимит ему не писан.
    resp = post_json(Client(), f"{BASE}/agreements",
                     card_body(line, counterparty), **auth(admin_token()))
    assert resp.status_code == 201, resp.content


def test_totals_in_the_card_do_not_add_up_and_nothing_objects(scenario):
    """Без НДС 99 999 999 999 + НДС 99 999 999 ≠ всего 99 999 999.

    Фиксирую фактическое поведение: сервер принимает несводимую тройку сумм.
    Считает их фронт, бэкенд их только хранит.
    """
    line, counterparty = scenario
    resp = post_json(Client(), f"{BASE}/agreements",
                     card_body(line, counterparty), **auth(admin_token()))
    assert resp.status_code == 201, resp.content
    d = resp.json()
    assert (Decimal(d["amount_without_vat"]) + Decimal(d["vat_amount"])
            != Decimal(d["amount"]))


def test_arithmetically_consistent_variant_at_zero_point_one_percent(scenario):
    """Та же карточка со сведёнными суммами: база 99 999 999 999 при 0,1 %."""
    line, counterparty = scenario
    base = Decimal("99999999999.00")
    vat = (base * Decimal("0.001")).quantize(Decimal("0.01"))   # 100 000 000.00
    total = base + vat                                          # 100 099 999 999.00
    resp = post_json(Client(), f"{BASE}/agreements", card_body(
        line, counterparty,
        amount_without_vat=str(base), vat_amount=str(vat), amount=str(total),
    ), **auth(admin_token()))
    assert resp.status_code == 201, resp.content
    d = resp.json()
    assert Decimal(d["vat_amount"]) == Decimal("100000000.00")
    assert Decimal(d["amount"]) == Decimal("100099999999.00")
    assert (Decimal(d["amount_without_vat"]) + Decimal(d["vat_amount"])
            == Decimal(d["amount"]))


def test_payload_exactly_as_the_form_computes_it(scenario):
    """Карточка в том виде, в каком её посчитает и отправит форма.

    База 99 999 999 999 при 0,1 % → НДС 100 000 000,00, всего
    100 099 999 999,00, гар. удержание 5 % от «всего». Числа сверены с
    калькулятором AgreementCreate.tsx (JS float на этом порядке точен).
    """
    line, counterparty = scenario
    resp = post_json(Client(), f"{BASE}/agreements", card_body(
        line, counterparty,
        amount_without_vat="99999999999.00",
        vat_amount="100000000.00",
        amount="100099999999.00",
        retention_amount="5004999999.95",
    ), **auth(admin_token()))
    assert resp.status_code == 201, resp.content
    d = resp.json()
    assert Decimal(d["amount"]) == Decimal("100099999999.00")
    assert Decimal(d["retention_amount"]) == Decimal("5004999999.95")
    assert (Decimal(d["amount"]) * Decimal("0.05")).quantize(Decimal("0.01")) \
        == Decimal(d["retention_amount"])
    # Аванса нет — обе величины остаются пустыми.
    assert d["advance_percentage"] is None
    assert d["advance_amount_planned"] is None
    assert d["has_advance"] is False


def test_the_card_survives_a_reread_and_an_edit(scenario):
    """GET после POST и PATCH «уточнить» → конкретная дата."""
    line, counterparty = scenario
    created = post_json(Client(), f"{BASE}/agreements",
                        card_body(line, counterparty), **auth(admin_token()))
    agreement_id = created.json()["id"]

    fetched = Client().get(f"{BASE}/agreements/{agreement_id}", **auth(token()))
    assert fetched.status_code == 200, fetched.content

    # POST отдаёт объект, только что собранный в памяти, поэтому суммы в нём
    # ровно те строки, что прислал клиент («99999999»); GET читает их из БД,
    # где NUMERIC(18,2) уже квантовал («99999999.00»). Значение то же, запись
    # разная — сравнивать ответы строка-в-строку нельзя.
    MONEY = ("amount", "amount_without_vat", "vat_amount", "retention_rate",
             "vat_rate", "advance_percentage", "advance_amount_planned",
             "retention_amount")
    a, b = created.json(), fetched.json()
    for key in MONEY:
        if a[key] is None or b[key] is None:
            assert a[key] == b[key], key
        else:
            assert Decimal(a[key]) == Decimal(b[key]), key
    assert {k: v for k, v in a.items() if k not in MONEY} ==            {k: v for k, v in b.items() if k not in MONEY}

    # Срок исполнения уточнили: комментарий сменился датой.
    from .helpers import patch_json
    resp = patch_json(Client(), f"{BASE}/agreements/{agreement_id}",
                      {"end_date": "2026-12-31", "term_comment": ""},
                      **auth(admin_token()))
    assert resp.status_code == 200, resp.content
    assert resp.json()["end_date"] == "2026-12-31"
    # start_date 28.05.2026 < end_date 31.12.2026 — правило порядка довольно.
    assert resp.json()["start_date"] == "2026-05-28"
