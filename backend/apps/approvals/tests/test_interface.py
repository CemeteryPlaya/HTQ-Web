"""Публичный ``interface.py`` домена «Запросы» — контракт для соседей.

Первый потребитель — ``apps.contracts`` (договор/счёт по заявке). Проверяется
то, ради чего файл существует: наружу уходят простые ``dict``, строка бюджета
достаётся из формы по виджету ``budget_line_ref``, а список одобренных не
ходит в БД за версией на каждую заявку.
"""

import pytest
from django.core.cache import cache
from django.db.models import Model

from apps.approvals import interface
from apps.approvals.models import RequestActivity, RequestStatus
from apps.core.models import ServiceStatus
from apps.core.services import ServiceDisabled

from .helpers import make_instance, make_template

SCHEMA = {"fields": [
    {"key": "budget", "type": "budget_line_ref", "label": "Бюджет"},
    {"key": "rows", "type": "group", "label": "Строки", "fields": [
        {"key": "line", "type": "budget_line_ref", "label": "Бюджет строки"},
    ]},
]}


@pytest.mark.django_db
def test_brief_is_a_plain_dict_with_the_budget_line_from_the_form():
    template = make_template(schema=SCHEMA)
    instance = make_instance(template, status=RequestStatus.APPROVED,
                             values={"budget": 42, "rows": [{"line": 7}]})

    brief = interface.get_request_brief(instance.pk)
    assert not isinstance(brief, Model)
    assert brief["code"] == instance.code
    assert brief["status"] == "approved"
    assert brief["template_name"] == template.name
    # Первое заполненное значение виджета — верхний уровень раньше группы.
    assert brief["budget_line_id"] == 42
    assert interface.get_request_brief(9999) is None


@pytest.mark.django_db
def test_budget_line_falls_back_to_group_rows_and_ignores_junk():
    template = make_template(schema=SCHEMA)
    in_group = make_instance(template, status=RequestStatus.APPROVED,
                             values={"budget": None, "rows": [{"line": 7}]})
    junk = make_instance(template, status=RequestStatus.APPROVED,
                         values={"budget": "abc", "rows": [{"line": True}]})
    assert interface.get_request_brief(in_group.pk)["budget_line_id"] == 7
    assert interface.get_request_brief(junk.pk)["budget_line_id"] is None


@pytest.mark.django_db
def test_list_approved_requests_filters_and_batches(django_assert_max_num_queries):
    template = make_template(schema=SCHEMA)
    with_line = make_instance(template, status=RequestStatus.APPROVED,
                              values={"budget": 42})
    make_instance(template, status=RequestStatus.APPROVED, values={"budget": None})
    make_instance(template, status=RequestStatus.PENDING, values={"budget": 42})
    plain = make_instance(make_template(slug="otpusk-2"), status=RequestStatus.APPROVED)

    # Заявки + версии + гейт сервиса: число запросов не растёт с числом заявок.
    with django_assert_max_num_queries(4):
        rows = interface.list_approved_requests()
    assert [row["id"] for row in rows] == [with_line.pk]

    everything = interface.list_approved_requests(with_budget_line=False)
    assert {row["id"] for row in everything} >= {with_line.pk, plain.pk}
    assert all(row["status"] == "approved" for row in everything)


@pytest.mark.django_db
def test_log_linked_document_writes_the_feed_or_reports_missing():
    instance = make_instance(make_template())
    assert interface.log_linked_document(
        instance.pk, kind="agreement", document_id=5, title="Договор Д-1",
        url="/contracts/agreements/5", actor_id=7) is True
    event = RequestActivity.objects.get(request=instance,
                                        event_type=interface.EVENT_DOCUMENT_LINKED)
    assert event.actor_id == 7
    assert event.payload == {"kind": "agreement", "document_id": 5,
                             "title": "Договор Д-1", "url": "/contracts/agreements/5"}
    assert interface.log_linked_document(
        9999, kind="agreement", document_id=5, title="x", url="/x", actor_id=7) is False


@pytest.mark.django_db
def test_interface_raises_service_disabled():
    instance = make_instance(make_template())
    assert interface.get_request_brief(instance.pk) is not None
    ServiceStatus.objects.update_or_create(app_label="approvals",
                                           defaults={"enabled": False})
    cache.clear()
    with pytest.raises(ServiceDisabled):
        interface.get_request_brief(instance.pk)
