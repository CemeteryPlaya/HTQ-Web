"""tenancy_status — слепок раскладки тенантных таблиц (roadmap §3, п.5).

Команда только читает: её результат до и после выкатки должен совпадать по
составу таблиц и компаний, иначе выкатка что-то унесла.
"""

import json
from io import StringIO

import pytest
from django.core.management import call_command

from htqweb.tenancy.context import schema_for


@pytest.mark.django_db
def test_json_snapshot_lists_registry_and_both_schemas(company_schema):
    out = StringIO()
    call_command("tenancy_status", "--json", stdout=out)
    data = json.loads(out.getvalue())

    company = next(c for c in data["companies"] if c["slug"] == company_schema["slug"])
    assert company["schema_exists"] is True
    assert company["schema"] == schema_for(company_schema["slug"])

    schema = schema_for(company_schema["slug"])
    # Тестовая база лежит в раскладке ДО bootstrap: те же таблицы есть и в
    # public, и в схеме компании — слепок обязан показать обе, не выбирая.
    assert "contracts_agreement" in data["schemas"]["public"]["tables"]
    assert "contracts_agreement" in data["schemas"][schema]["tables"]
    assert "signoff_approvalroute" in data["schemas"][schema]["tables"]
    assert set(data["schemas"][schema]["apps"]) == {"hr", "tasks", "contracts", "signoff"}
    assert data["exact"] is False


@pytest.mark.django_db
def test_text_output_names_each_company_and_schema(company_schema):
    out = StringIO()
    call_command("tenancy_status", stdout=out)
    text = out.getvalue()
    assert company_schema["slug"] in text
    assert schema_for(company_schema["slug"]) in text
    assert "Сводки holding" in text


@pytest.mark.django_db
def test_exact_mode_counts_rows(company_schema):
    out = StringIO()
    call_command("tenancy_status", "--json", "--exact", stdout=out)
    data = json.loads(out.getvalue())
    schema = schema_for(company_schema["slug"])
    assert data["exact"] is True
    assert data["schemas"][schema]["tables"]["signoff_approvalroute"] == 0


def test_tenant_tables_skip_holding_readers_but_keep_the_real_tables():
    """Тот же сторож, что и у ``tenancy_bootstrap``: читатели холдинга
    (``managed=False``, ``db_table`` совпадает с таблицей компании) не
    таблицы и в слепке считаться не должны — иначе ``hr_employee`` и
    ``tasks_task`` перечислялись бы в аппке дважды. Вторая проверка
    обязательна: одно «нет дублей» прошло бы и на пустом списке."""
    from apps.companies.management.commands.tenancy_status import tenant_tables

    listed = tenant_tables()
    for label, tables in listed.items():
        assert len(tables) == len(set(tables)), (label, tables)
    assert "hr_employee" in listed["hr"]
    assert "tasks_task" in listed["tasks"]
    assert "tasks_task_labels" in listed["tasks"]
    assert "contracts_budget" in listed["contracts"]
