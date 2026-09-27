"""Строковый ключ объекта: signoff согласует и строки с UUID-ключом.

Документы модуля БЗО (``apps.bpp``) заводятся с UUID-ключами (мастер-план
D-05), а ``ApprovalProcess.subject_id`` был целым. Теперь ключ хранится
строкой — канонической строкой ключа модели. Колбэки предметной аппки
получают его в типе ключа её модели, поэтому аппки с целыми ключами
(contracts, approvals, hr) не меняются.
"""

from __future__ import annotations

import pytest
from django.test import Client

from apps.signoff import interface
from apps.signoff.models import ApprovalProcess, ApprovalState, Quorum
from apps.signoff.services import engine, registry
from apps.signoff.tests.helpers import (
    BASE,
    admin_token,
    auth,
    make_doc,
    make_route,
    make_user,
    post_json,
    task_for,
    user_token,
)
from apps.signoff.tests.testapp import hooks
from apps.signoff.tests.testapp.models import ProbeDoc, UuidProbeDoc

pytestmark = pytest.mark.django_db

UUID_SUBJECT = UuidProbeDoc.SIGNOFF_SUBJECT_TYPE


@pytest.fixture(autouse=True)
def _reset_calls():
    hooks.reset()
    yield
    hooks.reset()


def _single_stage(user, subject_type=UUID_SUBJECT):
    return make_route([(1, "Единственный", Quorum.ALL, [user.pk])], subject_type=subject_type)


def test_uuid_subject_goes_through_the_whole_route():
    a, b = make_user("a"), make_user("b")
    doc = UuidProbeDoc.objects.create(title="Счёт")
    make_route([(1, "Первый", Quorum.ALL, [a.pk]), (2, "Второй", Quorum.ALL, [b.pk])],
               subject_type=UUID_SUBJECT)

    process = engine.start(subject_type=UUID_SUBJECT, subject_id=doc.pk, initiator_id=99)
    assert ApprovalProcess.objects.get(pk=process.pk).subject_id == str(doc.pk)

    engine.act(task_id=task_for(process, a.pk).pk, actor_id=a.pk, decision=engine.APPROVE)
    engine.act(task_id=task_for(process, b.pk).pk, actor_id=b.pk, decision=engine.APPROVE)

    doc.refresh_from_db()
    assert doc.approval_state == ApprovalState.APPROVED
    assert interface.approval_state_of(UUID_SUBJECT, str(doc.pk)) == ApprovalState.APPROVED
    # Колбэк получает ключ в типе ключа модели — UUID, а не строку.
    assert hooks.UUID_CALLS == [("started", doc.pk), ("approved", doc.pk)]


def test_integer_subject_callbacks_still_receive_an_int():
    a = make_user("a")
    doc = make_doc()
    _single_stage(a, subject_type=ProbeDoc.SIGNOFF_SUBJECT_TYPE)

    process = engine.start(subject_type=ProbeDoc.SIGNOFF_SUBJECT_TYPE, subject_id=doc.pk)

    assert ApprovalProcess.objects.get(pk=process.pk).subject_id == str(doc.pk)
    assert ("started", doc.pk) in hooks.CALLS
    assert all(isinstance(subject_id, int) for _kind, subject_id in hooks.CALLS)


def test_one_object_one_key_whatever_the_spelling():
    """``5``, ``"5"``, ``"05"`` — один объект; UUID в любом регистре — тоже.
    Иначе второе написание обошло бы индекс «один идущий процесс на объект»."""
    a = make_user("a")
    doc = UuidProbeDoc.objects.create(title="Счёт")
    _single_stage(a)
    engine.start(subject_type=UUID_SUBJECT, subject_id=str(doc.pk).upper())

    assert interface.get_process_for(UUID_SUBJECT, doc.pk) is not None
    with pytest.raises(engine.SignoffError):
        engine.start(subject_type=UUID_SUBJECT, subject_id=str(doc.pk))

    assert registry.storage_key(ProbeDoc.SIGNOFF_SUBJECT_TYPE, "05") == "5"
    assert registry.storage_key(ProbeDoc.SIGNOFF_SUBJECT_TYPE, 5) == "5"


def test_garbage_key_is_a_conflict_not_a_crash():
    with pytest.raises(registry.UnknownSubject):
        engine.start(subject_type=ProbeDoc.SIGNOFF_SUBJECT_TYPE, subject_id="abc")
    assert issubclass(registry.BadSubjectId, registry.UnknownSubject)


def test_awaiting_and_decided_ids_come_back_in_the_key_type_of_the_model():
    a = make_user("a")
    doc = UuidProbeDoc.objects.create(title="Счёт")
    _single_stage(a)
    process = engine.start(subject_type=UUID_SUBJECT, subject_id=doc.pk)

    assert interface.list_awaiting_subject_ids(a.pk, UUID_SUBJECT) == [doc.pk]
    engine.act(task_id=task_for(process, a.pk).pk, actor_id=a.pk, decision=engine.APPROVE)
    assert interface.list_decided_subject_ids(a.pk, UUID_SUBJECT) == [doc.pk]
    assert interface.is_participant(a.pk, UUID_SUBJECT, str(doc.pk))


def test_api_filters_by_a_string_key_and_answers_with_strings():
    a = make_user("a")
    doc = UuidProbeDoc.objects.create(title="Счёт")
    _single_stage(a)
    engine.start(subject_type=UUID_SUBJECT, subject_id=doc.pk, initiator_id=a.pk)

    response = Client().get(
        f"{BASE}/processes",
        {"subject_type": UUID_SUBJECT, "subject_id": str(doc.pk)},
        **auth(admin_token()))

    assert response.status_code == 200
    assert [row["subject_id"] for row in response.json()] == [str(doc.pk)]


def test_api_answers_an_empty_list_for_a_key_the_type_cannot_have():
    response = Client().get(
        f"{BASE}/processes",
        {"subject_type": ProbeDoc.SIGNOFF_SUBJECT_TYPE, "subject_id": "abc"},
        **auth(admin_token()))
    assert (response.status_code, response.json()) == (200, [])


def test_vote_options_reach_a_uuid_subject_in_its_key_type():
    """Сверх плана этапа 0: варианты голоса (B1.3) тоже получают ключ в типе
    модели. Варианты ищутся по ключу-UUID — пришла бы строка, их бы не
    нашлось, и голос не спросили бы вовсе."""
    a, b = make_user("a"), make_user("b")
    doc = UuidProbeDoc.objects.create(title="Договор")
    hooks.OPTIONS[doc.pk] = [{"key": "original", "label": "Исходный"},
                             {"key": "offer:1", "label": "Альтернатива"}]
    make_route([(1, "Первый", Quorum.ALL, [a.pk]), (2, "Второй", Quorum.ALL, [b.pk])],
               subject_type=UUID_SUBJECT)
    process = engine.start(subject_type=UUID_SUBJECT, subject_id=doc.pk)

    card = Client().get(f"{BASE}/processes/{process.pk}", **auth(user_token(a))).json()
    assert [o["key"] for o in card["options"]] == ["original", "offer:1"]
    task = task_for(process, a.pk)
    missing = post_json(Client(), f"{BASE}/tasks/{task.pk}/decision",
                        {"decision": "approve"}, **auth(user_token(a)))
    assert missing.status_code == 422

    engine.act(task_id=task.pk, actor_id=a.pk, decision=engine.APPROVE, option_key="offer:1")
    engine.act(task_id=task_for(process, b.pk).pk, actor_id=b.pk,
               decision=engine.APPROVE, option_key="offer:1")

    assert hooks.OPTION_VOTES == [(doc.pk, 1, a.pk, "offer:1"), (doc.pk, 2, b.pk, "offer:1")]
    final = interface.final_option(UUID_SUBJECT, str(doc.pk).upper())
    assert (final["key"], final["actor_id"]) == ("offer:1", b.pk)
