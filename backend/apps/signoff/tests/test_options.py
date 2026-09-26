"""Голос за вариант: «согласовать исходный» или «согласовать альтернативу».

Общая возможность движка (мастер-план БЗО, B1.3; Q-C12, D-26): предметная
аппка объявляет варианты (``options``), может отвергнуть голос за вариант
(``check_option``) и получает каждый голос для своей записи (``on_option``);
голос хранится и на запросе — ``option_key``/``option_label``.
"""

from __future__ import annotations

import dataclasses

import pytest
from django.test import Client

from apps.signoff import interface
from apps.signoff.models import ApprovalTask, Quorum
from apps.signoff.services import engine, registry
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
from apps.signoff.tests.testapp.models import ProbeDoc

pytestmark = pytest.mark.django_db

ORIGINAL = {"key": "original", "label": "Исходный документ"}
OFFER = {"key": "offer:1", "label": "Альтернатива АП-2026-000001"}


@pytest.fixture(autouse=True)
def _reset_calls():
    hooks.reset()
    yield
    hooks.reset()


def _two_stages():
    a, b = make_user("a"), make_user("b")
    make_route([(1, "Первый", Quorum.ALL, [a.pk]), (2, "Второй", Quorum.ALL, [b.pk])])
    doc = make_doc()
    hooks.OPTIONS[doc.pk] = [ORIGINAL, OFFER]
    process = engine.start(subject_type=SUBJECT, subject_id=doc.pk)
    return a, b, doc, process


def _decide(user, process, **body):
    task = task_for(process, user.pk)
    return post_json(Client(), f"{BASE}/tasks/{task.pk}/decision",
                     {"decision": "approve", **body}, **auth(user_token(user)))


def test_without_options_approve_needs_no_key():
    a = make_user("a")
    make_route([(1, "Единственный", Quorum.ALL, [a.pk])])
    doc = make_doc()
    process = engine.start(subject_type=SUBJECT, subject_id=doc.pk)

    engine.act(task_id=task_for(process, a.pk).pk, actor_id=a.pk, decision=engine.APPROVE)

    assert ApprovalTask.objects.get(stage__process=process).option_key == ""
    assert hooks.OPTION_VOTES == []
    assert interface.final_option(SUBJECT, doc.pk) is None


def test_the_card_lists_the_options_and_the_vote_is_recorded_twice():
    a, b, doc, process = _two_stages()

    card = Client().get(f"{BASE}/processes/{process.pk}", **auth(user_token(a))).json()
    assert card["options"] == [ORIGINAL, OFFER]

    assert _decide(a, process, option_key=OFFER["key"]).status_code == 200

    task = ApprovalTask.objects.get(stage__process=process, user_id=a.pk)
    assert (task.option_key, task.option_label) == (OFFER["key"], OFFER["label"])
    # Доменная запись голоса: объект, этап, кто, за что.
    assert hooks.OPTION_VOTES == [(doc.pk, 1, a.pk, OFFER["key"])]
    # Голос предыдущего этапа виден следующему.
    card = Client().get(f"{BASE}/processes/{process.pk}", **auth(user_token(b))).json()
    first = card["stages"][0]["tasks"][0]
    assert (first["option_key"], first["option_label"]) == (OFFER["key"], OFFER["label"])


def test_approve_without_a_key_is_422_and_changes_nothing():
    a, _b, _doc, process = _two_stages()

    response = _decide(a, process)

    assert response.status_code == 422
    assert "выберите" in response.json()["detail"]
    assert task_for(process, a.pk).option_key == ""
    assert hooks.OPTION_VOTES == []


def test_unknown_option_is_422():
    a, _b, _doc, process = _two_stages()

    response = _decide(a, process, option_key="offer:999")

    assert response.status_code == 422
    assert "обновите страницу" in response.json()["detail"]


def test_the_subject_can_refuse_a_vote_with_its_own_reason():
    a, _b, doc, process = _two_stages()
    hooks.OPTIONS[doc.pk] = [ORIGINAL, {"key": hooks.OPTION_BLOCKED, "label": "Нельзя"}]

    response = _decide(a, process, option_key=hooks.OPTION_BLOCKED)

    assert response.status_code == 422
    assert response.json()["detail"] == "за этот вариант голосовать нельзя"


def test_reject_needs_no_key():
    a, _b, _doc, process = _two_stages()

    engine.act(task_id=task_for(process, a.pk).pk, actor_id=a.pk,
               decision=engine.REJECT, comment="не подходит")

    assert hooks.OPTION_VOTES == []


def test_the_last_stage_decides():
    a, b, doc, process = _two_stages()
    _decide(a, process, option_key=OFFER["key"])
    _decide(b, process, option_key=ORIGINAL["key"])

    final = interface.final_option(SUBJECT, doc.pk)

    assert (final["key"], final["label"], final["actor_id"]) == (
        ORIGINAL["key"], ORIGINAL["label"], b.pk)


def test_a_failing_domain_record_rolls_the_decision_back(monkeypatch):
    a, _b, _doc, process = _two_stages()

    def broken(*_args):
        raise RuntimeError("журнал голосов недоступен")

    monkeypatch.setitem(registry._SUBJECTS, SUBJECT,
                        dataclasses.replace(registry.get_subject(SUBJECT), on_option=broken))

    with pytest.raises(RuntimeError):
        engine.act(task_id=task_for(process, a.pk).pk, actor_id=a.pk,
                   decision=engine.APPROVE, option_key=OFFER["key"])

    assert task_for(process, a.pk).option_key == ""


def test_option_hooks_without_options_are_refused_at_registration():
    with pytest.raises(ValueError, match="без options"):
        registry.register_subject(
            SUBJECT, label="Без вариантов", model=ProbeDoc,
            check_option=lambda subject_id, key: None)
