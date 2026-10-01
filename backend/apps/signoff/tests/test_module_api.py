"""API signoff для модуля БЗО (мастер-план, B1.3): массовое решение,
«Сейчас у», очередь пользователя, предсогласованные этапы."""

from __future__ import annotations

import pytest
from django.test import Client

from apps.core.models import ServiceStatus
from apps.hr.models import Employee
from apps.signoff import interface
from apps.signoff.models import (
    ApprovalEvent,
    ApprovalProcess,
    ApprovalTask,
    ProcessState,
    Quorum,
    StageState,
)
from apps.signoff.services import engine, holders
from apps.signoff.tests.helpers import (
    BASE,
    SUBJECT,
    auth,
    make_doc,
    make_route,
    make_user,
    post_json,
    task_for,
    user_token,
)
from apps.signoff.tests.testapp import hooks

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _reset_calls():
    hooks.reset()
    yield
    hooks.reset()


def _start(**kwargs):
    doc = make_doc()
    process = engine.start(subject_type=SUBJECT, subject_id=doc.pk, **kwargs)
    return doc, process


# ── decide_many ─────────────────────────────────────────────────────────

def test_decide_many_keeps_going_past_a_refusal():
    a, b = make_user("a"), make_user("b")
    make_route([(1, "Этап", Quorum.ANY, [a.pk])])
    _, first = _start()
    _, second = _start()
    foreign = make_user("foreign")
    make_route([(1, "Чужой", Quorum.ANY, [foreign.pk])], subject_type="testapp.uuiddoc")

    results = interface.decide_many(actor_id=a.pk, items=[
        {"task_id": task_for(first, a.pk).pk, "decision": "approve"},
        {"task_id": 999_999, "decision": "approve"},
        {"task_id": task_for(second, a.pk).pk, "decision": "reject",
         "comment": "Не нужно"},
    ])

    assert [row["ok"] for row in results] == [True, False, True]
    assert "не найден" in results[1]["error"]
    assert ApprovalProcess.objects.get(pk=first.pk).state == ProcessState.APPROVED
    rejected = ApprovalProcess.objects.get(pk=second.pk)
    assert rejected.state == ProcessState.REJECTED
    assert ApprovalTask.objects.get(stage__process=second).comment == "Не нужно"
    assert b.pk  # второй пользователь в решениях не участвовал


def test_batch_endpoint_takes_items_with_their_own_option_and_comment():
    a = make_user("a")
    make_route([(1, "Этап", Quorum.ANY, [a.pk])])
    doc, with_options = _start()
    hooks.OPTIONS[doc.pk] = [{"key": "original", "label": "Исходный"},
                             {"key": "offer:1", "label": "Альтернатива"}]
    _, plain = _start()

    resp = post_json(Client(), f"{BASE}/tasks/batch-decision", {"items": [
        {"task_id": task_for(with_options, a.pk).pk, "decision": "approve",
         "option_key": "offer:1"},
        {"task_id": task_for(plain, a.pk).pk, "decision": "rework",
         "comment": "Уточните сумму"},
    ]}, **auth(user_token(a)))

    assert resp.status_code == 200, resp.content
    assert [row["ok"] for row in resp.json()] == [True, True]
    assert interface.final_option(SUBJECT, doc.pk)["key"] == "offer:1"
    assert ApprovalTask.objects.get(stage__process=plain).comment == "Уточните сумму"


def test_batch_endpoint_keeps_the_old_shape_and_refuses_a_mix():
    a = make_user("a")
    make_route([(1, "Этап", Quorum.ANY, [a.pk])])
    _, process = _start()
    task_id = task_for(process, a.pk).pk

    mixed = post_json(Client(), f"{BASE}/tasks/batch-decision",
                      {"task_ids": [task_id], "decision": "approve",
                       "items": [{"task_id": task_id, "decision": "approve"}]},
                      **auth(user_token(a)))
    assert mixed.status_code == 422
    old = post_json(Client(), f"{BASE}/tasks/batch-decision",
                    {"task_ids": [task_id], "decision": "approve"}, **auth(user_token(a)))
    assert old.status_code == 200 and old.json() == [{"task_id": task_id, "ok": True,
                                                      "error": None}]


# ── «Сейчас у» ──────────────────────────────────────────────────────────

def test_current_holders_follow_the_route():
    a, b = make_user("a"), make_user("b")
    make_route([(1, "ТД", Quorum.ANY, [a.pk]), (2, "ОД", Quorum.ANY, [b.pk])])
    doc, process = _start()
    stage = process.stages.get(order=1)

    first = interface.current_holders(SUBJECT, [doc.pk, "abc"])
    assert list(first) == [str(doc.pk)]
    row = first[str(doc.pk)]
    assert row["stage"] == "ТД"
    assert row["users"] == [{"id": a.pk, "name": row["users"][0]["name"]}]
    assert row["position"] == f"Signoff {a.username}"
    assert row["since"] == stage.activated_at and row["no_executor"] is False

    engine.act(task_id=task_for(process, a.pk).pk, actor_id=a.pk, decision=engine.APPROVE)
    after = interface.current_holders(SUBJECT, [doc.pk])[str(doc.pk)]
    assert after["stage"] == "ОД"
    assert [user["id"] for user in after["users"]] == [b.pk]

    engine.act(task_id=task_for(process, b.pk).pk, actor_id=b.pk, decision=engine.APPROVE)
    assert interface.current_holders(SUBJECT, [doc.pk]) == {}


def test_current_holders_mark_a_stage_without_an_executor():
    vacant = make_user("vacant")
    Employee.objects.filter(user_id=vacant.pk).update(is_deleted=True)
    route = make_route([(1, "ФД", Quorum.ANY, [vacant.pk])])
    route.lazy_resolution = True
    route.save()
    doc, _process = _start()

    row = interface.current_holders(SUBJECT, [doc.pk])[str(doc.pk)]

    assert row["users"] == [] and row["no_executor"] is True and row["stage"] == "ФД"


def test_count_no_executor_counts_waiting_processes_of_its_prefix():
    """Блок администрирования «Обзора» БЗО: идущие процессы, стоящие на этапе
    «Нет исполнителя», — только своих типов."""
    vacant = make_user("vacant")
    Employee.objects.filter(user_id=vacant.pk).update(is_deleted=True)
    route = make_route([(1, "ФД", Quorum.ANY, [vacant.pk])])
    route.lazy_resolution = True
    route.save()
    _start(), _start()

    assert interface.count_no_executor(SUBJECT) == 2
    assert interface.count_no_executor("bpp.") == 0


# ── очередь пользователя ────────────────────────────────────────────────

def test_pending_for_user_shows_only_active_stages():
    a, b = make_user("a"), make_user("b")
    make_route([(1, "Первый", Quorum.ANY, [a.pk]), (2, "Второй", Quorum.ANY, [b.pk])])
    doc, process = _start()

    assert interface.pending_for_user(b.pk) == []
    rows = interface.pending_for_user(a.pk)
    assert [(row["subject_id"], row["title"]) for row in rows] == [(str(doc.pk), doc.title)]
    assert rows[0]["since"] == process.stages.get(order=1).activated_at
    assert rows[0]["url"] == f"/probe/{doc.pk}"


# ── источник ежедневной сводки (D-23) ───────────────────────────────────

def test_signoff_is_registered_as_a_tenant_digest_source():
    from apps.notifications.services import digest

    fn, tenant, section, _landing = digest._SOURCES["signoff"]
    assert fn is holders.digest_items and tenant is True
    # Сводка считает пункты без раздела пунктами согласования: заголовок
    # «Ждут вашего решения» и ссылка /signoff держатся на этом.
    assert section is None


def test_digest_items_name_the_document_and_the_stage():
    a = make_user("a")
    make_route([(1, "Первый", Quorum.ANY, [a.pk])])
    doc, process = _start()

    assert holders.digest_items(a.pk) == [{
        "title": f"{doc.title} — Первый",
        "url": f"/probe/{doc.pk}",
        "since": process.created_at,
    }]


def test_digest_items_are_empty_while_signoff_is_disabled():
    a = make_user("a")
    make_route([(1, "Первый", Quorum.ANY, [a.pk])])
    _start()
    ServiceStatus.objects.update_or_create(
        app_label="signoff", defaults={"enabled": False, "message": "выключено"})

    assert holders.digest_items(a.pk) == []


# ── предсогласованные этапы (D-26) ──────────────────────────────────────

def test_preapproved_stage_creates_no_tasks_and_the_process_starts_after_it():
    fd, gd = make_user("fd"), make_user("gd")
    make_route([(1, "ГД", Quorum.ANY, [gd.pk]), (2, "ФД", Quorum.ANY, [fd.pk])])

    _, process = _start(preapproved=[{"position_id": gd.pk, "actor_id": gd.pk,
                                      "label": "Согласовано при выборе альтернативы"}])

    process.refresh_from_db()
    first = process.stages.get(order=1)
    assert first.state == StageState.APPROVED and not first.tasks.exists()
    assert process.current_order == 2
    event = ApprovalEvent.objects.get(process=process, kind="stage_preapproved")
    assert event.payload["label"] == "Согласовано при выборе альтернативы"
    assert event.payload["position_ids"] == [gd.pk] and event.payload["actor_ids"] == [gd.pk]
    assert [task.user_id for task in ApprovalTask.objects.filter(stage__process=process)] == [fd.pk]


def test_everything_preapproved_approves_the_process_at_once():
    gd = make_user("gd")
    make_route([(1, "ГД", Quorum.ANY, [gd.pk])])

    doc, process = _start(preapproved=[{"position_id": gd.pk, "actor_id": gd.pk,
                                        "label": "Согласовано при выборе альтернативы"}])

    assert ApprovalProcess.objects.get(pk=process.pk).state == ProcessState.APPROVED
    assert ("approved", doc.pk) in hooks.CALLS


def test_lazy_route_does_not_ask_a_preapproved_position():
    fd, gd = make_user("fd"), make_user("gd")
    Employee.objects.filter(user_id=gd.pk).update(is_deleted=True)  # ГД в отпуске
    route = make_route([(1, "ФД", Quorum.ANY, [fd.pk]), (2, "ГД", Quorum.ANY, [gd.pk])])
    route.lazy_resolution = True
    route.save()
    _, process = _start(preapproved=[{"position_id": gd.pk, "actor_id": gd.pk}])

    engine.act(task_id=task_for(process, fd.pk).pk, actor_id=fd.pk, decision=engine.APPROVE)

    # Предсогласованная должность не даёт «Нет исполнителя», даже если пуста.
    assert ApprovalProcess.objects.get(pk=process.pk).state == ProcessState.APPROVED


def test_preapproving_a_position_the_route_does_not_have_is_a_conflict():
    a = make_user("a")
    make_route([(1, "Этап", Quorum.ANY, [a.pk])])

    with pytest.raises(engine.PreapprovalMismatch):
        _start(preapproved=[{"position_id": 987_654}])
    assert not ApprovalProcess.objects.exists()
