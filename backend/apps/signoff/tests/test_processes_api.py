"""HTTP-слой исполнения: ``/api/signoff/v1/processes|tasks``.

Семантику переходов проверяет ``test_engine.py``; здесь — контракт HTTP:
коды ответов, права и то, что решение принимает НАЗВАННЫЙ в маршруте
человек, а не носитель админского флага.
"""

from __future__ import annotations

import pytest

from apps.signoff.models import ApprovalState, ProcessState, Quorum
from apps.signoff.services import engine
from apps.signoff.tests.helpers import (
    BASE,
    admin_token,
    auth,
    make_doc,
    make_route,
    make_user,
    post_json,
    simple_route,
    task_for,
    token,
    user_token,
)
from apps.signoff.tests.testapp import hooks
from apps.signoff.tests.testapp.models import ProbeDoc

pytestmark = pytest.mark.django_db

SUBJECT = ProbeDoc.SIGNOFF_SUBJECT_TYPE


@pytest.fixture(autouse=True)
def _reset_calls():
    hooks.reset()
    yield
    hooks.reset()


def _start(client, doc, *, initiator=None):
    body = {"subject_type": SUBJECT, "subject_id": doc.pk}
    if initiator is not None:
        body["initiator_id"] = initiator
    return post_json(client, f"{BASE}/processes", body, **auth(admin_token()))


# ── Запуск ──────────────────────────────────────────────────────────────

def test_start_returns_the_card_with_stages_and_subject_title(client):
    a = make_user("a")
    doc = make_doc("Договор №7")
    simple_route(a.pk)

    started = _start(client, doc)
    assert started.status_code == 201, started.content
    body = started.json()
    assert body["state"] == ProcessState.PENDING
    assert body["current_order"] == 1
    assert len(body["stages"]) == 1
    # Заголовок и ссылка приходят из describe() предметной аппки — signoff
    # не умеет построить их сам.
    assert body["subject_title"] == "Договор №7"
    assert body["subject_url"] == f"/probe/{doc.pk}"


def test_start_without_a_route_is_409(client):
    doc = make_doc()
    assert _start(client, doc).status_code == 409


def test_start_twice_is_409(client):
    a = make_user("a")
    doc = make_doc()
    simple_route(a.pk)

    assert _start(client, doc).status_code == 201
    clash = _start(client, doc)
    assert clash.status_code == 409
    assert "уже находится на согласовании" in clash.json()["detail"]


def test_start_is_admin_only(client):
    """Общий эндпоинт принимает любой subject_id любого типа — отдавать его
    всем значило бы обойти доменные права мимо их владельца. Штатный путь
    отправки появится в предметной аппке."""
    a = make_user("a")
    doc = make_doc()
    simple_route(a.pk)

    forbidden = post_json(client, f"{BASE}/processes",
                          {"subject_type": SUBJECT, "subject_id": doc.pk},
                          **auth(token()))
    assert forbidden.status_code == 403


# ── Решения ─────────────────────────────────────────────────────────────

def test_the_named_approver_decides_without_being_an_admin(client):
    """Суть модуля: согласует тот, кто назван в маршруте."""
    a = make_user("a")
    doc = make_doc()
    simple_route(a.pk)
    process = engine.start(subject_type=SUBJECT, subject_id=doc.pk)

    decided = post_json(client, f"{BASE}/tasks/{task_for(process, a.pk).pk}/decision",
                        {"decision": "approve", "comment": "ок"},
                        **auth(user_token(a)))
    assert decided.status_code == 200, decided.content
    assert decided.json()["state"] == ProcessState.APPROVED

    doc.refresh_from_db()
    assert doc.approval_state == ApprovalState.APPROVED
    assert doc.published is True


def test_an_admin_cannot_decide_someone_elses_task(client):
    """Админский флаг не делает человека согласующим."""
    a = make_user("a")
    doc = make_doc()
    simple_route(a.pk)
    process = engine.start(subject_type=SUBJECT, subject_id=doc.pk)

    refused = post_json(client, f"{BASE}/tasks/{task_for(process, a.pk).pk}/decision",
                        {"decision": "approve"}, **auth(admin_token()))
    assert refused.status_code == 409
    assert "другому согласующему" in refused.json()["detail"]


def test_rejection_closes_the_process(client):
    a, b = make_user("a"), make_user("b")
    doc = make_doc()
    make_route([
        (1, "Первый", Quorum.ALL, [a.pk]),
        (2, "Второй", Quorum.ALL, [b.pk]),
    ])
    process = engine.start(subject_type=SUBJECT, subject_id=doc.pk)

    rejected = post_json(client, f"{BASE}/tasks/{task_for(process, a.pk).pk}/decision",
                         {"decision": "reject", "comment": "не согласен"},
                         **auth(user_token(a)))
    assert rejected.status_code == 200
    assert rejected.json()["state"] == ProcessState.REJECTED

    doc.refresh_from_db()
    assert doc.approval_state == ApprovalState.REJECTED


def test_deciding_twice_is_409(client):
    a = make_user("a")
    doc = make_doc()
    simple_route(a.pk)
    process = engine.start(subject_type=SUBJECT, subject_id=doc.pk)
    task_id = task_for(process, a.pk).pk

    post_json(client, f"{BASE}/tasks/{task_id}/decision",
              {"decision": "approve"}, **auth(user_token(a)))
    again = post_json(client, f"{BASE}/tasks/{task_id}/decision",
                      {"decision": "approve"}, **auth(user_token(a)))
    assert again.status_code == 409


def test_an_unknown_decision_is_422(client):
    a = make_user("a")
    doc = make_doc()
    simple_route(a.pk)
    process = engine.start(subject_type=SUBJECT, subject_id=doc.pk)

    bad = post_json(client, f"{BASE}/tasks/{task_for(process, a.pk).pk}/decision",
                    {"decision": "maybe"}, **auth(user_token(a)))
    assert bad.status_code == 422


def test_deciding_an_unknown_task_is_404(client):
    a = make_user("a")
    bad = post_json(client, f"{BASE}/tasks/999999/decision",
                    {"decision": "approve"}, **auth(user_token(a)))
    assert bad.status_code == 404


# ── Инбокс ──────────────────────────────────────────────────────────────

def test_inbox_shows_only_what_awaits_the_caller_right_now(client):
    a, b = make_user("a"), make_user("b")
    doc = make_doc("Заявка на бюджет")
    make_route([
        (1, "Первый", Quorum.ALL, [a.pk]),
        (2, "Второй", Quorum.ALL, [b.pk]),
    ])
    engine.start(subject_type=SUBJECT, subject_id=doc.pk, initiator_id=42)

    mine = client.get(f"{BASE}/tasks/mine", **auth(user_token(a)))
    assert mine.status_code == 200
    assert len(mine.json()) == 1
    row = mine.json()[0]
    assert row["stage_name"] == "Первый"
    assert row["subject_title"] == "Заявка на бюджет"
    assert row["subject_url"] == f"/probe/{doc.pk}"
    assert row["initiator_id"] == 42

    # У второго очередь ещё не наступила — запрос в БД есть, но показывать
    # его как «ждёт вас» нельзя: до него может и не дойти.
    assert client.get(f"{BASE}/tasks/mine", **auth(user_token(b))).json() == []


def test_inbox_empties_once_the_stage_is_decided(client):
    a = make_user("a")
    doc = make_doc()
    simple_route(a.pk)
    process = engine.start(subject_type=SUBJECT, subject_id=doc.pk)

    assert len(client.get(f"{BASE}/tasks/mine", **auth(user_token(a))).json()) == 1
    engine.act(task_id=task_for(process, a.pk).pk, actor_id=a.pk,
               decision=engine.APPROVE)
    assert client.get(f"{BASE}/tasks/mine", **auth(user_token(a))).json() == []


def test_quorum_any_clears_the_inbox_of_the_other_approver(client):
    a, b = make_user("a"), make_user("b")
    doc = make_doc()
    simple_route(a.pk, b.pk, quorum=Quorum.ANY)
    process = engine.start(subject_type=SUBJECT, subject_id=doc.pk)

    engine.act(task_id=task_for(process, a.pk).pk, actor_id=a.pk,
               decision=engine.APPROVE)
    # Запрос второго погашен, а не висит у него навсегда.
    assert client.get(f"{BASE}/tasks/mine", **auth(user_token(b))).json() == []


# ── Чтение и отзыв ──────────────────────────────────────────────────────

def test_processes_can_be_looked_up_by_subject(client):
    a = make_user("a")
    doc = make_doc()
    simple_route(a.pk)
    engine.start(subject_type=SUBJECT, subject_id=doc.pk)

    found = client.get(
        f"{BASE}/processes?subject_type={SUBJECT}&subject_id={doc.pk}",
        **auth(token()))
    assert found.status_code == 200
    assert len(found.json()) == 1
    assert found.json()[0]["subject_id"] == doc.pk


def test_unknown_process_is_404(client):
    assert client.get(f"{BASE}/processes/999999", **auth(token())).status_code == 404


def test_the_initiator_can_cancel_without_being_an_admin(client):
    a = make_user("a")
    initiator = make_user("initiator")
    doc = make_doc()
    simple_route(a.pk)
    process = engine.start(subject_type=SUBJECT, subject_id=doc.pk,
                           initiator_id=initiator.pk)

    cancelled = post_json(client, f"{BASE}/processes/{process.pk}/cancel", {},
                          **auth(user_token(initiator)))
    assert cancelled.status_code == 200
    assert cancelled.json()["state"] == ProcessState.CANCELLED

    doc.refresh_from_db()
    # Отзыв — не отказ: объект снова черновик.
    assert doc.approval_state == ApprovalState.DRAFT


def test_a_stranger_cannot_cancel(client):
    a = make_user("a")
    stranger = make_user("stranger")
    doc = make_doc()
    simple_route(a.pk)
    process = engine.start(subject_type=SUBJECT, subject_id=doc.pk,
                           initiator_id=make_user("initiator").pk)

    forbidden = post_json(client, f"{BASE}/processes/{process.pk}/cancel", {},
                          **auth(user_token(stranger)))
    assert forbidden.status_code == 403


def test_an_admin_can_cancel_anyones_process(client):
    a = make_user("a")
    doc = make_doc()
    simple_route(a.pk)
    process = engine.start(subject_type=SUBJECT, subject_id=doc.pk,
                           initiator_id=make_user("initiator").pk)

    cancelled = post_json(client, f"{BASE}/processes/{process.pk}/cancel", {},
                          **auth(admin_token()))
    assert cancelled.status_code == 200


def test_cancelling_a_finished_process_is_409(client):
    a = make_user("a")
    doc = make_doc()
    simple_route(a.pk)
    process = engine.start(subject_type=SUBJECT, subject_id=doc.pk,
                           initiator_id=a.pk)
    engine.act(task_id=task_for(process, a.pk).pk, actor_id=a.pk,
               decision=engine.APPROVE)

    bad = post_json(client, f"{BASE}/processes/{process.pk}/cancel", {},
                    **auth(user_token(a)))
    assert bad.status_code == 409


# ── Возврат на доработку ────────────────────────────────────────────────
#
# Решение ``rework`` принимается по СВОЕЙ задаче (``/tasks/:id/decision``),
# а этот эндпоинт — про уже закрытый круг: единственный способ отпереть
# согласованный или отклонённый объект.

def test_rework_as_a_decision_unlocks_the_object(client):
    a = make_user("a")
    doc = make_doc()
    simple_route(a.pk)
    process = engine.start(subject_type=SUBJECT, subject_id=doc.pk)

    reworked = post_json(client, f"{BASE}/tasks/{task_for(process, a.pk).pk}/decision",
                         {"decision": "rework", "comment": "исправьте сумму"},
                         **auth(user_token(a)))
    assert reworked.status_code == 200, reworked.content
    assert reworked.json()["state"] == ProcessState.REWORK

    doc.refresh_from_db()
    assert doc.approval_state == ApprovalState.REWORK


def test_an_approver_can_return_a_finished_process_for_rework(client):
    a = make_user("a")
    doc = make_doc()
    simple_route(a.pk)
    process = engine.start(subject_type=SUBJECT, subject_id=doc.pk,
                           initiator_id=make_user("initiator").pk)
    engine.act(task_id=task_for(process, a.pk).pk, actor_id=a.pk,
               decision=engine.APPROVE)

    returned = post_json(client, f"{BASE}/processes/{process.pk}/rework",
                         {"comment": "не та программа"}, **auth(user_token(a)))
    assert returned.status_code == 200, returned.content
    assert returned.json()["state"] == ProcessState.REWORK

    doc.refresh_from_db()
    assert doc.approval_state == ApprovalState.REWORK


def test_an_admin_can_return_anyones_process_for_rework(client):
    a = make_user("a")
    doc = make_doc()
    simple_route(a.pk)
    process = engine.start(subject_type=SUBJECT, subject_id=doc.pk)
    engine.act(task_id=task_for(process, a.pk).pk, actor_id=a.pk,
               decision=engine.APPROVE)

    returned = post_json(client, f"{BASE}/processes/{process.pk}/rework", {},
                         **auth(admin_token()))
    assert returned.status_code == 200, returned.content


def test_the_initiator_alone_cannot_return_for_rework(client):
    """Отзыв и возврат — разные права: свою заявку забирают, пока её не
    рассмотрели, а отпереть решённое по собственному желанию значило бы
    обойти чужое решение."""
    a = make_user("a")
    initiator = make_user("initiator")
    doc = make_doc()
    simple_route(a.pk)
    process = engine.start(subject_type=SUBJECT, subject_id=doc.pk,
                           initiator_id=initiator.pk)
    engine.act(task_id=task_for(process, a.pk).pk, actor_id=a.pk,
               decision=engine.APPROVE)

    forbidden = post_json(client, f"{BASE}/processes/{process.pk}/rework", {},
                          **auth(user_token(initiator)))
    assert forbidden.status_code == 403

    doc.refresh_from_db()
    assert doc.approval_state == ApprovalState.APPROVED


def test_returning_a_running_process_for_rework_is_409(client):
    a = make_user("a")
    doc = make_doc()
    simple_route(a.pk)
    process = engine.start(subject_type=SUBJECT, subject_id=doc.pk)

    bad = post_json(client, f"{BASE}/processes/{process.pk}/rework", {},
                    **auth(user_token(a)))
    assert bad.status_code == 409
    assert "ещё идёт" in bad.json()["detail"]
