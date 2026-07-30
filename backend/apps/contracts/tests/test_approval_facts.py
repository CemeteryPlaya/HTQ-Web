"""Факты, по которым signoff ветвит маршруты объектов contracts.

Механику ветвления проверяет ``apps/signoff/tests`` на своей нейтральной
модели; здесь — то, что добавляет именно эта аппка: КАКИЕ факты она снимает
со своих трёх моделей и что они доезжают до движка в пригодном виде.

Читаются факты через ``registry`` — то есть ровно тем путём, которым их
возьмёт ``engine.start``, а не прямым вызовом функции из ``approval_hooks``:
проверять надо стык, а не тело функции.
"""

from __future__ import annotations

import pytest

from apps.contracts.models import Agreement, Budget, Counterparty
from apps.contracts.tests.helpers import (
    make_administrator,
    make_agreement,
    make_budget,
    make_counterparty,
    make_country,
    make_line,
    make_program,
)
from apps.signoff.services import registry

pytestmark = pytest.mark.django_db


def fields_by_key(subject_type: str) -> dict:
    return {field["key"]: field for field in registry.fields_for(subject_type)}


# ═══════════════════════════════════════════════════════════════════════
# Бюджет
# ═══════════════════════════════════════════════════════════════════════

def test_budget_reports_the_country_of_its_administrator():
    """Тот самый факт, ради которого ветвление и делалось."""
    kazakhstan = make_country("Казахстан", "KZ")
    budget = make_budget(administrator=make_administrator(country=kazakhstan))

    facts = registry.facts_for(Budget.SIGNOFF_SUBJECT_TYPE, budget.pk)

    assert facts["admin_country_id"] == kazakhstan.pk


def test_budget_amount_is_the_sum_of_its_lines_as_a_plain_number():
    """Денег на самом Budget нет — сумма считается по строкам. И приходит
    ``float``, а не ``Decimal``: факты сохраняются в JSONField."""
    budget = make_budget()
    # Разные программы: у пары (name, expense_item) уникальный индекс, и две
    # строки с программой по умолчанию уронили бы тест на нём.
    make_line(budget=budget, amount="1000000.00")
    make_line(budget=budget, program=make_program("Наука", "Реактивы"),
              amount="500000.00")

    facts = registry.facts_for(Budget.SIGNOFF_SUBJECT_TYPE, budget.pk)

    assert facts["amount"] == 1500000.0
    assert isinstance(facts["amount"], float)


def test_budget_country_options_follow_the_reference_book():
    """`fact_fields` — функция, а не константа, ровно ради этого: страну
    завели после старта процесса, и она обязана появиться в редакторе."""
    make_country("Казахстан", "KZ")
    before = len(fields_by_key(Budget.SIGNOFF_SUBJECT_TYPE)["admin_country_id"]["options"])

    make_country("Узбекистан", "UZ")
    after = fields_by_key(Budget.SIGNOFF_SUBJECT_TYPE)["admin_country_id"]["options"]

    assert len(after) == before + 1
    assert "Узбекистан" in [option["label"] for option in after]


# ═══════════════════════════════════════════════════════════════════════
# Договор — две разные страны
# ═══════════════════════════════════════════════════════════════════════

def test_agreement_separates_the_two_countries_it_has():
    """Главная ловушка домена: у договора страна администратора бюджета и
    страна контрагента — РАЗНЫЕ (казахстанский проект закупается у турецкого
    поставщика). Общий ключ `country_id` означал бы, что настраивающий
    маршрут выберет одну из них наугад и никогда об этом не узнает.
    """
    kazakhstan = make_country("Казахстан", "KZ")
    turkey = make_country("Турция", "TR")
    line = make_line(administrator=make_administrator(country=kazakhstan))
    agreement = make_agreement(
        line=line, counterparty=make_counterparty(country=turkey, bin_iin="999"))

    facts = registry.facts_for(Agreement.SIGNOFF_SUBJECT_TYPE, agreement.pk)

    assert facts["admin_country_id"] == kazakhstan.pk
    assert facts["counterparty_country_id"] == turkey.pk


def test_agreement_fields_label_the_two_countries_distinguishably():
    """Ключи разные — но выбирать поле человек будет по подписи, и она тоже
    обязана различать эти две страны."""
    make_country("Казахстан", "KZ")
    fields = fields_by_key(Agreement.SIGNOFF_SUBJECT_TYPE)

    assert fields["admin_country_id"]["label"] != fields["counterparty_country_id"]["label"]
    assert fields["admin_country_id"]["type"] == "choice"
    assert fields["counterparty_country_id"]["type"] == "choice"


def test_agreement_amount_and_payment_type_are_branchable():
    line = make_line()
    agreement = make_agreement(line=line, amount="400000.00")

    facts = registry.facts_for(Agreement.SIGNOFF_SUBJECT_TYPE, agreement.pk)

    assert facts["amount"] == 400000.0
    assert facts["payment_type"] == "postpayment"
    assert "payment_type" in fields_by_key(Agreement.SIGNOFF_SUBJECT_TYPE)


# ═══════════════════════════════════════════════════════════════════════
# Контрагент
# ═══════════════════════════════════════════════════════════════════════

def test_counterparty_reports_its_own_country_and_vat():
    turkey = make_country("Турция", "TR")
    counterparty = make_counterparty(country=turkey, vat=True)

    facts = registry.facts_for(Counterparty.SIGNOFF_SUBJECT_TYPE, counterparty.pk)

    assert facts == {"counterparty_country_id": turkey.pk, "vat": True}


# ═══════════════════════════════════════════════════════════════════════
# Общее
# ═══════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("model", [Budget, Counterparty, Agreement])
def test_facts_of_a_deleted_object_are_empty_not_an_exception(model):
    """Объект удалили между отправкой и запуском. Условный маршрут откажет
    внятным «не сошлось ни одно условие», безусловный отработает как прежде —
    решать судьбу висячей ссылки не задача снятия фактов."""
    assert registry.facts_for(model.SIGNOFF_SUBJECT_TYPE, 10_000_000) == {}


@pytest.mark.parametrize("model", [Budget, Counterparty, Agreement])
def test_every_declared_field_is_actually_reported(model):
    """Схема и факты обязаны совпадать по ключам: поле, объявленное в
    редакторе, но не приходящее в фактах, даёт условие, которое роняет запуск
    ConditionError'ом — причём у пользователя, а не у настройщика."""
    make_country("Казахстан", "KZ")
    line = make_line()
    row = {
        Budget: lambda: line.budget,
        Counterparty: lambda: make_counterparty(bin_iin="777"),
        Agreement: lambda: make_agreement(line=line),
    }[model]()

    facts = registry.facts_for(model.SIGNOFF_SUBJECT_TYPE, row.pk)
    declared = set(fields_by_key(model.SIGNOFF_SUBJECT_TYPE))

    assert declared <= set(facts), f"объявлено, но не сообщается: {declared - set(facts)}"
