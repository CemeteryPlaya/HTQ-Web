"""Виджет ``budget_line_ref`` — единственная дверь approvals в contracts.

Проверяется контракт моста, а не UI: схема с виджетом публикуется; при
отправке ссылка сверяется с ``apps.contracts.interface`` (чужой id,
закрытый бюджет, снятый администратор — 422 с путём поля); таблица данных
получает подпись, а не число; выключенный contracts даёт 503 — но только
форме, в которой такой виджет есть.

Фабрики строк бюджета берутся из ``apps.contracts.tests.helpers``: тесты из
проверки изоляции исключены (``test_app_isolation.py``), а заводить в
approvals собственную копию контрактных моделей было бы второй правдой.
"""

import pytest
from django.core.cache import cache
from django.test import Client

from apps.approvals.models import RequestReferenceRow, RequestStatus
from apps.approvals.services import budget_line_refs, template_data_table
from apps.approvals.services.form_schema import validate_form_schema
from apps.contracts.models import BudgetStatus
from apps.contracts.tests.helpers import make_administrator, make_line, make_program
from apps.core.models import ServiceStatus

from .helpers import BASE, auth, make_instance, make_template, post_json

REF = {"key": "budget", "type": "budget_line_ref", "label": "Бюджет",
       "required": True}
ITEMS = {
    "key": "items", "type": "group", "label": "Позиции", "repeatable": True,
    "fields": [
        {"key": "name", "type": "text", "label": "ТРУ"},
        {"key": "qty", "type": "number", "label": "Кол-во"},
        {"key": "unit", "type": "dropdown", "label": "Ед.",
         "options": ["шт", "кг", "т"]},
        {"key": "needed_by", "type": "date", "label": "Дата потребности"},
    ],
}
PURCHASE_SCHEMA = {"fields": [REF, ITEMS]}


def _submit(client, instance_id):
    return client.post(f"{BASE}/instances/{instance_id}/submit/", **auth())


def _contracts(enabled: bool) -> None:
    ServiceStatus.objects.update_or_create(
        app_label="contracts", defaults={"enabled": enabled})
    # service_status() держит ответ в 5-секундном кэше; в тесте ждать нечего.
    cache.clear()


# ── схема ────────────────────────────────────────────────────────────────

def test_schema_accepts_the_widget_top_level_and_inside_a_group():
    schema = validate_form_schema({"fields": [
        REF,
        {"key": "rows", "type": "group", "label": "Строки",
         "fields": [{"key": "line", "type": "budget_line_ref", "label": "Бюджет"}]},
    ]})
    assert {f.type for f in schema.fields} == {"budget_line_ref", "group"}
    assert schema.all_keys == {"budget", "rows", "line"}


def test_iter_refs_walks_group_rows_with_a_dotted_path():
    schema = validate_form_schema({"fields": [
        REF,
        {"key": "rows", "type": "group", "label": "Строки",
         "fields": [{"key": "line", "type": "budget_line_ref", "label": "Бюджет"}]},
    ]})
    values = {"budget": 5, "rows": [{"line": 6}, {"line": None}, "мусор"]}
    assert list(budget_line_refs.iter_refs(schema, values)) == [
        ("budget", 5), ("rows.line", 6), ("rows.line", None),
    ]


@pytest.mark.django_db
def test_template_with_the_widget_publishes():
    template = make_template(schema=PURCHASE_SCHEMA)
    assert template.current_version_id is not None


# ── отправка ─────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_submit_with_a_live_budget_line_goes_pending():
    line = make_line()
    template = make_template(schema=PURCHASE_SCHEMA)
    instance = make_instance(template, values={
        "budget": line.pk,
        "items": [{"name": "Ноутбук", "qty": 2, "unit": "шт",
                   "needed_by": "2026-10-01"}],
    })
    resp = _submit(Client(), instance.id)
    # Отправка отдаёт карточку процесса signoff (как submit в contracts).
    assert resp.status_code == 201, resp.content
    assert resp.json()["state"] == "pending"
    instance.refresh_from_db()
    assert instance.status == RequestStatus.PENDING


@pytest.mark.django_db
def test_submit_with_an_unknown_budget_line_is_422():
    template = make_template(schema=PURCHASE_SCHEMA)
    instance = make_instance(template, values={"budget": 9999, "items": []})
    resp = _submit(Client(), instance.id)
    assert resp.status_code == 422
    assert "budget_line_ref 'budget'" in resp.json()["detail"]
    assert "9999" in resp.json()["detail"]


@pytest.mark.django_db
def test_submit_against_a_closed_budget_is_422():
    line = make_line()
    line.budget.status = BudgetStatus.CLOSED
    line.budget.save(update_fields=["status"])
    template = make_template(schema=PURCHASE_SCHEMA)
    instance = make_instance(template, values={"budget": line.pk, "items": []})
    resp = _submit(Client(), instance.id)
    assert resp.status_code == 422
    assert "closed budget" in resp.json()["detail"]


@pytest.mark.django_db
def test_submit_against_an_inactive_administrator_is_422():
    admin = make_administrator(project_name="Проект Б")
    line = make_line(administrator=admin)
    admin.is_active = False
    admin.save(update_fields=["is_active"])
    template = make_template(schema=PURCHASE_SCHEMA)
    instance = make_instance(template, values={"budget": line.pk, "items": []})
    resp = _submit(Client(), instance.id)
    assert resp.status_code == 422
    assert "inactive budget administrator" in resp.json()["detail"]


@pytest.mark.django_db
def test_submit_rejects_a_non_id_value_before_asking_contracts():
    template = make_template(schema=PURCHASE_SCHEMA)
    for junk in ("abc", True, 2.5):
        instance = make_instance(template, values={"budget": junk, "items": []})
        resp = _submit(Client(), instance.id)
        assert resp.status_code == 422, junk
        assert "is not a budget line id" in resp.json()["detail"]


@pytest.mark.django_db
def test_widget_inside_a_group_is_checked_per_row():
    schema = {"fields": [
        {"key": "rows", "type": "group", "label": "Строки", "fields": [
            {"key": "line", "type": "budget_line_ref", "label": "Бюджет"},
        ]},
    ]}
    line = make_line()
    template = make_template(schema=schema)
    instance = make_instance(template, values={
        "rows": [{"line": line.pk}, {"line": 9999}],
    })
    resp = _submit(Client(), instance.id)
    assert resp.status_code == 422
    assert "budget_line_ref 'rows.line'" in resp.json()["detail"]


# ── таблица данных ───────────────────────────────────────────────────────

@pytest.mark.django_db
def test_data_table_shows_the_budget_line_as_a_label():
    line = make_line(program=make_program(name="Образование", code="P-1"))
    template = make_template(schema=PURCHASE_SCHEMA)
    template_data_table.ensure_source_for_template(template)
    template_data_table.sync_columns_for_template(template, PURCHASE_SCHEMA)
    instance = make_instance(template, values={"budget": line.pk, "items": []})

    assert _submit(Client(), instance.id).status_code == 201

    row = RequestReferenceRow.objects.get(instance_id=instance.id)
    expected = (f"{line.budget.administrator.display_name} — P-1 Образование "
                f"({line.budget.period_year}, {line.budget.currency})")
    assert row.data["Бюджет"] == expected


@pytest.mark.django_db
def test_data_table_label_degrades_when_contracts_is_off():
    """Подпись — не проверка: недоступный сосед стоит подписи, а не строки."""
    line = make_line()
    template = make_template(schema=PURCHASE_SCHEMA)
    template_data_table.ensure_source_for_template(template)
    template_data_table.sync_columns_for_template(template, PURCHASE_SCHEMA)
    instance = make_instance(template, values={"budget": line.pk, "items": []})

    _contracts(False)
    template_data_table.sync_row_for_instance(instance)
    row = RequestReferenceRow.objects.get(instance_id=instance.id)
    assert row.data["Бюджет"] == f"Строка бюджета #{line.pk}"


# ── выключенный contracts ────────────────────────────────────────────────

@pytest.mark.django_db
def test_submit_is_503_when_contracts_is_off():
    line = make_line()
    template = make_template(schema=PURCHASE_SCHEMA)
    instance = make_instance(template, values={"budget": line.pk, "items": []})

    _contracts(False)
    resp = _submit(Client(), instance.id)
    assert resp.status_code == 503
    body = resp.json()
    assert body["code"] == "service_disabled"
    assert body["service"] == "contracts"
    instance.refresh_from_db()
    assert instance.status == RequestStatus.DRAFT

    _contracts(True)
    assert _submit(Client(), instance.id).status_code == 201


@pytest.mark.django_db
def test_forms_without_the_widget_do_not_depend_on_contracts():
    """Отпуск не должен ломаться оттого, что договоры на обслуживании."""
    template = make_template()  # simple_schema: одно число
    instance = make_instance(template)
    _contracts(False)
    assert _submit(Client(), instance.id).status_code == 201


@pytest.mark.django_db
def test_an_empty_optional_widget_does_not_ask_contracts():
    schema = {"fields": [{**REF, "required": False}]}
    template = make_template(schema=schema)
    instance = make_instance(template, values={"budget": None})
    _contracts(False)
    assert _submit(Client(), instance.id).status_code == 201


@pytest.mark.django_db
def test_request_creation_is_unaffected_by_contracts_being_off():
    """Черновик заводится без проверки ссылки — проверка при отправке."""
    template = make_template(schema=PURCHASE_SCHEMA)
    _contracts(False)
    resp = post_json(Client(), f"{BASE}/instances/",
                     {"template_id": template.id, "title": "Закуп",
                      "form_values": {"budget": 1, "items": []}}, **auth())
    assert resp.status_code == 201
