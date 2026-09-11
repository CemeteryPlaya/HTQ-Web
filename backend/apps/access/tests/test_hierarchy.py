"""Задача 5 плана A: внешняя иерархия из дерева владения компаниями (§1.4).

Поля ``is_manager`` и ``external_hierarchy`` на должности заводит переработка
HR, а не эта стадия. Поэтому «сегодняшнее» поведение (пустой список у всех) и
«завтрашнее» (руководитель получает поддерево) проверяются по отдельности:
второе — подменой ответа кадрового интерфейса, то есть ровно того шва, через
который эти поля и приедут.
"""

import logging

import pytest

from apps.access.services import hierarchy


@pytest.fixture
def company_tree(db):
    """Холдинг → региональная → две сервисные, плюс чужая ветка."""
    from apps.companies.models import Company, CompanyKind

    holding = Company.objects.create(slug="htq-holding", name="Холдинг",
                                     kind=CompanyKind.HOLDING)
    kz = Company.objects.create(slug="htq-kz", name="КЗ", kind=CompanyKind.REGIONAL,
                                parent=holding)
    Company.objects.create(slug="kurly-kg", name="КГ", kind=CompanyKind.SERVICE,
                           parent=kz)
    Company.objects.create(slug="lonely", name="Сама по себе",
                           kind=CompanyKind.SERVICE)
    return holding


def _manager_brief(**extra):
    brief = {"id": 1, "full_name": "Иванов Иван", "department_id": 1,
             "position_id": 7, "position_title": "Директор", "status": "active"}
    brief.update(extra)
    return brief


# ── Обход дерева ──────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_companies_below_returns_whole_subtree(company_tree):
    assert hierarchy.companies_below("htq-holding") == ["htq-kz", "kurly-kg"]


@pytest.mark.django_db
def test_companies_below_stops_at_the_branch(company_tree):
    assert hierarchy.companies_below("htq-kz") == ["kurly-kg"]


@pytest.mark.django_db
def test_companies_below_of_a_leaf_is_empty(company_tree):
    assert hierarchy.companies_below("kurly-kg") == []


@pytest.mark.django_db
def test_sibling_branch_is_not_below(company_tree):
    assert "lonely" not in hierarchy.companies_below("htq-holding")


@pytest.mark.django_db
def test_cycle_in_company_tree_does_not_hang(company_tree):
    """Цикл, заведённый мимо приложения, не должен вешать разрешение прав.

    Осмысленного ответа на вопрос «кто ниже» в цикле не существует: по одному
    из путей ниже оказывается каждый. Проверяется поэтому не состав списка, а
    то, что вызов ЗАВЕРШАЕТСЯ и не возвращает саму компанию — разрешение прав
    выполняется на каждом запросе с гейтом, и зависание там недопустимо.
    """
    from apps.companies.models import Company

    holding = Company.objects.get(slug="htq-holding")
    kurly = Company.objects.get(slug="kurly-kg")
    # UPDATE в обход валидации — именно так цикл и заводится на практике.
    Company.objects.filter(pk=holding.pk).update(parent=kurly)

    below = hierarchy.companies_below("htq-kz")
    assert "htq-kz" not in below
    assert len(below) == len(set(below))
    assert "kurly-kg" in below


# ── Гейт «только руководители» ────────────────────────────────────────────


@pytest.mark.django_db
def test_plain_employee_has_no_subordinate_companies(
        user, employee_with_position, company_tree):
    assert hierarchy.subordinate_companies(user, "htq-holding") == []


@pytest.mark.django_db
def test_user_without_employee_card_has_no_subordinate_companies(user, company_tree):
    assert hierarchy.subordinate_companies(user, "htq-holding") == []


@pytest.mark.django_db
def test_no_company_context_means_empty(user, company_tree):
    assert hierarchy.subordinate_companies(user, None) == []


@pytest.mark.django_db
def test_manager_with_inherit_gets_the_subtree(user, company_tree, monkeypatch):
    """Договор с переработкой HR: два поля на должности включают иерархию."""
    from apps.hr import interface as hr

    monkeypatch.setattr(hr, "get_employee_brief",
                        lambda _uid: _manager_brief(is_manager=True,
                                                    external_hierarchy="inherit"))
    assert hierarchy.subordinate_companies(user, "htq-holding") == ["htq-kz", "kurly-kg"]


@pytest.mark.django_db
def test_manager_who_opted_out_gets_nothing(user, company_tree, monkeypatch):
    """Руководящая должность не обязана командовать нижестоящими компаниями."""
    from apps.hr import interface as hr

    monkeypatch.setattr(hr, "get_employee_brief",
                        lambda _uid: _manager_brief(is_manager=True,
                                                    external_hierarchy="none"))
    assert hierarchy.subordinate_companies(user, "htq-holding") == []


@pytest.mark.django_db
def test_non_manager_with_inherit_gets_nothing(user, company_tree, monkeypatch):
    """Оговорка «относится к руководителям» — обязательная часть правила 4."""
    from apps.hr import interface as hr

    monkeypatch.setattr(hr, "get_employee_brief",
                        lambda _uid: _manager_brief(is_manager=False,
                                                    external_hierarchy="inherit"))
    assert hierarchy.subordinate_companies(user, "htq-holding") == []


@pytest.mark.django_db
def test_disabled_hr_logs_fallback_and_returns_empty(
        user, company_tree, service_off, caplog):
    with caplog.at_level(logging.INFO, logger="htqweb.fallback"):
        with service_off("hr"):
            assert hierarchy.subordinate_companies(user, "htq-holding") == []
    assert "access.hierarchy.hr_unavailable" in caplog.text
