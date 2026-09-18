"""Личная аналитика: человек видит СВОИ заявки и только их.

Главное здесь — не арифметика, а граница: у ручки нет параметра «чья
статистика», и чужие заявки в неё не попадают ни при каких запросах. Всё
остальное (суммы, позиции) проверяется затем, чтобы страница не врала.
"""

import pytest
from django.test import Client

from apps.approvals.models import (
    RequestFormTemplate, RequestFormTemplateVersion, RequestInstance,
    RequestStatus, TemplateStatus,
)
from apps.approvals.services import personal_stats

from .helpers import BASE, auth, token

pytestmark = pytest.mark.django_db

ME, OTHER = 501, 502

SCHEMA = {"fields": [
    {"key": "items", "type": "group", "label": "Позиции", "repeatable": True,
     "summarize_keys": ["quantity"], "fields": [
         {"key": "name", "type": "text", "label": "ТРУ"},
         {"key": "quantity", "type": "number", "label": "Кол-во"},
         {"key": "unit", "type": "dropdown", "label": "Ед.", "options": ["шт", "кг"]},
     ]},
    {"key": "terms", "type": "group", "label": "Условия", "repeatable": False,
     "fields": [
         {"key": "amount", "type": "money", "label": "Сумма",
          "contributes_to_total": True},
     ]},
]}


def make_template(schema=None) -> RequestFormTemplate:
    template = RequestFormTemplate.objects.create(
        name="Заявка", slug=f"t-{RequestFormTemplate.objects.count()}",
        status=TemplateStatus.ACTIVE, created_by=ME)
    version = RequestFormTemplateVersion.objects.create(
        template=template, version=1, schema_json=schema or SCHEMA,
        workflow_json={})
    template.current_version_id = version.pk
    template.save(update_fields=["current_version_id"])
    return template


def make_request(template, *, initiator=ME, status=RequestStatus.APPROVED,
                 amount="0", values=None) -> RequestInstance:
    from django.utils import timezone
    return RequestInstance.objects.create(
        code=f"REQ-{RequestInstance.objects.count() + 1:04d}",
        template=template, template_version_id=template.current_version_id,
        initiator_id=initiator, status=status, total_amount=amount,
        currency="KZT", form_values_json=values or {},
        submitted_at=None if status == RequestStatus.DRAFT else timezone.now())


def items(values_items):
    return {"items": values_items, "terms": {"amount": "0"}}


# ── граница видимости ─────────────────────────────────────────────────

def test_only_my_own_requests_are_counted():
    template = make_template()
    make_request(template, initiator=ME, amount="100")
    make_request(template, initiator=ME, amount="200")
    make_request(template, initiator=OTHER, amount="9000.00")

    mine = personal_stats.for_user(ME)
    assert mine["submitted"] == 2
    # Деньги — с двумя знаками: это форма записи суммы, а не лишние нули.
    assert mine["amount"] == "300.00"

    # У соседа — своя картина, и она никак не пересекается.
    assert personal_stats.for_user(OTHER)["amount"] == "9000.00"


def test_the_endpoint_has_no_way_to_ask_for_someone_else(client=None):
    """Параметра «чья статистика» нет: что бы ни прислали, ответ про
    вызывающего. Это и есть вся защита — не фильтр, а отсутствие ручки."""
    template = make_template()
    make_request(template, initiator=ME, amount="100")
    make_request(template, initiator=OTHER, amount="9000.00")
    client = Client()

    for query in ("", "?user_id=502", "?initiator_id=502", "?actor=502"):
        resp = client.get(f"{BASE}/stats/mine{query}",
                          **auth(token(user_id=ME, sub=str(ME))))
        assert resp.status_code == 200, resp.content
        assert resp.json()["amount"] == "100.00"


def test_a_plain_user_cannot_read_company_wide_stats():
    """Общие разрезы — админские. Раньше они отвечали любому, и
    ``by-actor`` показывал, кто сколько подал по всей компании."""
    client = Client()
    plain = auth(token(user_id=ME, sub=str(ME)))
    for path in ("overview", "by-project", "by-template", "by-actor", "heatmap"):
        assert client.get(f"{BASE}/stats/{path}", **plain).status_code == 403
    assert client.get(f"{BASE}/stats/mine", **plain).status_code == 200


def test_since_narrows_the_window():
    """``?since=`` — левая граница по дате отправки; без неё сводка за всё
    время. Черновиков граница не касается: у них даты отправки нет."""
    import datetime as dt

    from django.utils import timezone

    template = make_template()
    old_one = make_request(template, amount="100")
    RequestInstance.objects.filter(pk=old_one.pk).update(
        submitted_at=timezone.now() - dt.timedelta(days=40))
    make_request(template, amount="50")

    assert personal_stats.for_user(ME)["amount"] == "150.00"
    recent = personal_stats.for_user(
        ME, since=timezone.now().date() - dt.timedelta(days=7))
    assert (recent["submitted"], recent["amount"]) == (1, "50.00")

    resp = Client().get(f"{BASE}/stats/mine?since=not-a-date",
                        **auth(token(user_id=ME, sub=str(ME))))
    assert resp.status_code == 422


# ── что показывает сводка ─────────────────────────────────────────────

def test_drafts_are_counted_apart_and_add_nothing_to_the_sum():
    """Неотправленное — ещё не заявка: в сумму не идёт, но человек должен
    видеть, что у него висят черновики."""
    template = make_template()
    make_request(template, amount="100")
    make_request(template, status=RequestStatus.DRAFT, amount="777")

    mine = personal_stats.for_user(ME)
    assert (mine["submitted"], mine["drafts"], mine["amount"]) == (1, 1, "100.00")


def test_statuses_and_templates_are_broken_out():
    template = make_template()
    make_request(template, status=RequestStatus.APPROVED, amount="100")
    make_request(template, status=RequestStatus.APPROVED, amount="50")
    make_request(template, status=RequestStatus.REJECTED, amount="30")

    mine = personal_stats.for_user(ME)
    assert mine["by_status"]["approved"] == {"count": 2, "amount": "150.00"}
    assert mine["by_status"]["rejected"] == {"count": 1, "amount": "30.00"}
    assert mine["by_template"][0]["count"] == 3
    assert mine["by_template"][0]["name"] == "Заявка"


def test_items_are_summed_by_name_and_unit():
    template = make_template()
    make_request(template, values=items([
        {"name": "Ноутбук", "quantity": 2, "unit": "шт"},
        {"name": "Кабель", "quantity": 100, "unit": "м"},
    ]))
    make_request(template, values=items([
        {"name": "Ноутбук", "quantity": 3, "unit": "шт"},
    ]))

    rows = {(r["name"], r["unit"]): r for r in personal_stats.for_user(ME)["items"]}
    assert rows[("Ноутбук", "шт")]["quantity"] == "5"
    assert rows[("Ноутбук", "шт")]["requests"] == 2
    assert rows[("Кабель", "м")]["requests"] == 1


def test_different_units_are_never_added_together():
    """«5 шт» и «3 кг» — разные строки: сложить их значило бы выдумать
    величину, которой нет."""
    template = make_template()
    make_request(template, values=items([
        {"name": "Трос", "quantity": 5, "unit": "шт"},
        {"name": "Трос", "quantity": 3, "unit": "кг"},
    ]))

    rows = {(r["name"], r["unit"]): r["quantity"]
            for r in personal_stats.for_user(ME)["items"]}
    assert rows == {("Трос", "шт"): "5", ("Трос", "кг"): "3"}


def test_a_row_without_a_name_is_skipped():
    template = make_template()
    make_request(template, values=items([
        {"name": "", "quantity": 9, "unit": "шт"},
        {"quantity": 4},
        {"name": "Мышь", "quantity": 1, "unit": "шт"},
    ]))
    assert [r["name"] for r in personal_stats.for_user(ME)["items"]] == ["Мышь"]


def test_a_broken_quantity_does_not_break_the_summary():
    """Значения приходят из формы, а форма переживала правки: нечисловое
    количество считаем нулём, но позицию показываем."""
    template = make_template()
    make_request(template, values=items([
        {"name": "Бумага", "quantity": "много", "unit": "шт"},
        {"name": "Бумага", "quantity": 5, "unit": "шт"},
    ]))
    (row,) = personal_stats.for_user(ME)["items"]
    assert (row["name"], row["quantity"]) == ("Бумага", "5")


def test_a_group_without_a_text_column_gives_no_items():
    """Назвать позицию нечем — строка «(без названия) × 7» бесполезна."""
    template = make_template({"fields": [
        {"key": "rows", "type": "group", "label": "Строки", "repeatable": True,
         "fields": [{"key": "qty", "type": "number", "label": "Кол-во"}]},
    ]})
    make_request(template, values={"rows": [{"qty": 7}]})
    assert personal_stats.for_user(ME)["items"] == []


def test_items_are_read_with_the_version_the_request_was_filled_on():
    """Заявка живёт со своей версией формы: после правки шаблона старые
    позиции обязаны считаться по прежней схеме."""
    template = make_template()
    old_request = make_request(template, values=items([
        {"name": "Стул", "quantity": 4, "unit": "шт"},
    ]))

    new_version = RequestFormTemplateVersion.objects.create(
        template=template, version=2, workflow_json={},
        schema_json={"fields": [
            {"key": "items", "type": "group", "label": "Позиции",
             "repeatable": True, "fields": [
                 {"key": "title", "type": "text", "label": "Что"},
                 {"key": "n", "type": "number", "label": "Сколько"},
             ]},
        ]})
    template.current_version_id = new_version.pk
    template.save(update_fields=["current_version_id"])
    make_request(template, values={"items": [{"title": "Стол", "n": 2}]})

    rows = {r["name"]: r["quantity"] for r in personal_stats.for_user(ME)["items"]}
    assert rows == {"Стул": "4", "Стол": "2"}
    assert old_request.template_version_id != new_version.pk
