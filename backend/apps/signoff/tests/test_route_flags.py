"""Флаги маршрута signoff (мастер-план БЗО, B1.2 / D-21, D-22; ТЗ §16.1).

Каждый флаг — своим сценарием; без флагов движок ведёт себя по-старому
(это держит весь прежний набор тестов). «Роли» в signoff — HR-должности:
у каждого пользователя тестов своя должность с тем же id (``make_user``).
"""

from __future__ import annotations

import datetime as dt

import pytest
from django.test import Client
from django.utils import timezone

from apps.hr.models import ActingAssignment, Department, Employee, Position
from apps.signoff.models import (
    ApprovalEvent,
    ApprovalProcess,
    ApprovalRoute,
    ApprovalTask,
    ProcessState,
    Quorum,
    StageState,
    TaskState,
)
from apps.signoff.services import engine
from apps.signoff.tests.helpers import (
    BASE,
    SUBJECT,
    admin_token,
    auth,
    make_doc,
    make_route,
    make_user,
    patch_json,
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


@pytest.fixture
def sent(monkeypatch):
    """Уведомления движка — списком ``(user_ids, payload)``, без мессенджера."""
    box: list[tuple[list[int], dict]] = []
    monkeypatch.setattr(engine, "_notify",
                        lambda user_ids, payload: box.append((list(user_ids), payload)))
    return box


def _flag(route: ApprovalRoute, **flags) -> ApprovalRoute:
    for key, value in flags.items():
        setattr(route, key, value)
    route.save()
    return route


def _start(author=None):
    return engine.start(subject_type=SUBJECT, subject_id=make_doc().pk,
                        initiator_id=author.pk if author else None)


def _events(process, kind: str) -> list[dict]:
    return [event.payload for event in
            ApprovalEvent.objects.filter(process=process, kind=kind).order_by("id")]


def _second_holder(position_owner, username: str):
    """Ещё один держатель должности ``position_owner`` (у каждого свой id)."""
    user = make_user(username)
    Employee.objects.filter(user_id=user.pk).update(
        position=Position.objects.get(pk=position_owner.pk))
    return user


def _acting(position_owner, user, *, days: int = 7):
    today = timezone.localdate()
    ActingAssignment.objects.create(
        position=Position.objects.get(pk=position_owner.pk),
        employee=Employee.objects.get(user_id=user.pk),
        date_from=today, date_to=today + dt.timedelta(days=days), basis="Приказ")


# ── без флагов ──────────────────────────────────────────────────────────

def test_flags_are_off_by_default_and_snapshotted():
    a = make_user("a")
    route = make_route([(1, "Этап", Quorum.ANY, [a.pk])])
    assert (route.forbid_self_approval, route.reject_comment_min, route.lazy_resolution,
            route.escalation_position_id) == (False, 0, False, None)

    process = _start(author=a)

    # Автор — единственный согласующий, и без флага он согласует сам, как раньше.
    assert list(ApprovalTask.objects.filter(stage__process=process)
                .values_list("user_id", flat=True)) == [a.pk]
    assert process.route_flags["forbid_self_approval"] is False
    engine.act(task_id=task_for(process, a.pk).pk, actor_id=a.pk, decision=engine.REJECT)


# ── BR-060: комментарий при отказе и возврате ───────────────────────────

def test_reject_and_rework_need_a_comment_of_the_route_length():
    a = make_user("a")
    _flag(make_route([(1, "Этап", Quorum.ANY, [a.pk])]), reject_comment_min=10)
    process = _start()
    task = task_for(process, a.pk)
    url = f"{BASE}/tasks/{task.pk}/decision"

    short = post_json(Client(), url, {"decision": "reject", "comment": "123456789 "},
                      **auth(user_token(a)))
    assert short.status_code == 422
    assert "не меньше 10 символов" in short.json()["detail"]
    rework = post_json(Client(), url, {"decision": "rework", "comment": ""},
                       **auth(user_token(a)))
    assert rework.status_code == 422
    assert ApprovalTask.objects.get(pk=task.pk).state == TaskState.PENDING

    ok = post_json(Client(), url, {"decision": "rework", "comment": "1234567890"},
                   **auth(user_token(a)))
    assert ok.status_code == 200, ok.content


def test_approve_needs_no_comment_under_the_rule():
    a = make_user("a")
    _flag(make_route([(1, "Этап", Quorum.ANY, [a.pk])]), reject_comment_min=10)
    process = _start()

    engine.act(task_id=task_for(process, a.pk).pk, actor_id=a.pk, decision=engine.APPROVE)

    assert ApprovalProcess.objects.get(pk=process.pk).state == ProcessState.APPROVED


def test_route_edit_does_not_change_a_running_process():
    a = make_user("a")
    route = make_route([(1, "Этап", Quorum.ANY, [a.pk])])
    process = _start()
    _flag(route, reject_comment_min=10)

    engine.act(task_id=task_for(process, a.pk).pk, actor_id=a.pk,
               decision=engine.REJECT, comment="нет")

    assert ApprovalProcess.objects.get(pk=process.pk).state == ProcessState.REJECTED


# ── BR-061: запрет самосогласования ─────────────────────────────────────

def test_author_is_dropped_when_the_position_has_another_holder():
    author = make_user("author")
    other = _second_holder(author, "other")
    _flag(make_route([(1, "ФД", Quorum.ANY, [author.pk])]), forbid_self_approval=True)

    process = _start(author=author)

    assert list(ApprovalTask.objects.filter(stage__process=process)
                .values_list("user_id", flat=True)) == [other.pk]


def test_acting_holder_signs_instead_of_the_author():
    author = make_user("author")
    acting = make_user("acting")
    _acting(author, acting)
    _flag(make_route([(1, "ФД", Quorum.ANY, [author.pk])]), forbid_self_approval=True)

    process = _start(author=author)

    task = ApprovalTask.objects.get(stage__process=process)
    assert (task.user_id, task.position_id) == (acting.pk, author.pk)


def test_escalation_takes_the_stage_when_nobody_else_holds_the_position():
    author, gd = make_user("author"), make_user("gd")
    _flag(make_route([(1, "ФД", Quorum.ANY, [author.pk])]),
          forbid_self_approval=True, escalation_position_id=gd.pk)

    process = _start(author=author)

    task = ApprovalTask.objects.get(stage__process=process)
    # Задача — у ГД, но кворум по-прежнему считается по роли этапа.
    assert (task.user_id, task.position_id) == (gd.pk, author.pk)
    assert _events(process, "self_approval_escalated")[0]["escalation_position_id"] == gd.pk


def test_author_who_is_the_escalation_itself_is_skipped_and_fd_notified(sent):
    gd, fd, next_one = make_user("gd"), make_user("fd"), make_user("next")
    _flag(make_route([(1, "ГД", Quorum.ANY, [gd.pk]), (2, "Далее", Quorum.ANY, [next_one.pk])]),
          forbid_self_approval=True, escalation_position_id=gd.pk,
          self_skip_notify_position_ids=[fd.pk])

    process = _start(author=gd)

    process.refresh_from_db()
    stages = {stage.order: stage for stage in process.stages.all()}
    assert stages[1].state == StageState.APPROVED and not stages[1].tasks.exists()
    assert stages[2].state == StageState.ACTIVE
    assert process.current_order == 2
    assert _events(process, "self_approval_skipped")[0]["position_ids"] == [gd.pk]
    assert _events(process, "stage_auto_approved")
    skipped = [users for users, payload in sent
               if payload["type"] == "signoff.self_approval_skipped"]
    assert skipped == [[fd.pk]]


def test_author_cannot_decide_even_with_a_task_made_before_the_flag():
    author = make_user("author")
    route = make_route([(1, "ФД", Quorum.ANY, [author.pk])])
    process = _start(author=author)
    ApprovalProcess.objects.filter(pk=process.pk).update(
        route_flags={**process.route_flags, "forbid_self_approval": True})
    task = task_for(process, author.pk)

    resp = post_json(Client(), f"{BASE}/tasks/{task.pk}/decision", {"decision": "approve"},
                     **auth(user_token(author)))

    assert resp.status_code == 403
    assert "автором которого вы являетесь" in resp.json()["detail"]
    assert route.pk  # маршрут не трогали


# ── ТЗ §16.1 п.2, п.5: ленивое разрешение и «Нет исполнителя» ───────────

def test_lazy_stage_is_resolved_on_activation():
    a = make_user("a")
    vacant = make_user("vacant-holder")
    Employee.objects.filter(user_id=vacant.pk).update(is_deleted=True)  # должность пуста
    _flag(make_route([(1, "Первый", Quorum.ANY, [a.pk]), (2, "Второй", Quorum.ANY, [vacant.pk])]),
          lazy_resolution=True)
    process = _start()
    assert not ApprovalTask.objects.filter(stage__order=2, stage__process=process).exists()

    acting = make_user("acting")
    _acting(vacant, acting)
    engine.act(task_id=task_for(process, a.pk).pk, actor_id=a.pk, decision=engine.APPROVE)

    second = process.stages.get(order=2)
    assert second.state == StageState.ACTIVE and second.activated_at is not None
    assert list(second.tasks.values_list("user_id", flat=True)) == [acting.pk]


def test_stage_without_an_executor_waits_and_notifies(sent):
    a, adm = make_user("a"), make_user("adm")
    vacant = make_user("vacant-holder")
    Employee.objects.filter(user_id=vacant.pk).update(is_deleted=True)
    _flag(make_route([(1, "Первый", Quorum.ANY, [a.pk]), (2, "Второй", Quorum.ANY, [vacant.pk])]),
          lazy_resolution=True, no_executor_notify_position_ids=[adm.pk])
    process = _start()

    engine.act(task_id=task_for(process, a.pk).pk, actor_id=a.pk, decision=engine.APPROVE)

    process.refresh_from_db()
    second = process.stages.get(order=2)
    assert process.state == ProcessState.PENDING and process.current_order == 2
    assert second.state == StageState.NO_EXECUTOR and not second.tasks.exists()
    assert _events(process, "no_executor")[0]["position_ids"] == [vacant.pk]
    assert [users for users, payload in sent if payload["type"] == "signoff.no_executor"] \
        == [[adm.pk]]

    # Назначили временного исполнителя — повторная попытка оживляет этап.
    acting = make_user("acting")
    _acting(vacant, acting)
    assert engine.retry_no_executor(process.pk) == 1
    second.refresh_from_db()
    assert second.state == StageState.ACTIVE
    assert list(second.tasks.values_list("user_id", flat=True)) == [acting.pk]
    assert engine.retry_no_executor(process.pk) == 0


def test_lazy_first_stage_without_an_executor_is_not_a_refusal():
    vacant = make_user("vacant-holder")
    Employee.objects.filter(user_id=vacant.pk).update(is_deleted=True)
    _flag(make_route([(1, "Первый", Quorum.ANY, [vacant.pk])]), lazy_resolution=True)

    process = _start()

    assert process.stages.get(order=1).state == StageState.NO_EXECUTOR
    assert process.pk in engine.pending_no_executor_process_ids()


def test_without_the_flag_a_vacant_position_is_still_a_refusal():
    vacant = make_user("vacant-holder")
    Employee.objects.filter(user_id=vacant.pk).update(is_deleted=True)
    make_route([(1, "Первый", Quorum.ANY, [vacant.pk])])

    with pytest.raises(engine.RouteUnusable):
        _start()


def test_cancel_closes_a_stage_that_waits_for_an_executor():
    vacant = make_user("vacant-holder")
    Employee.objects.filter(user_id=vacant.pk).update(is_deleted=True)
    _flag(make_route([(1, "Первый", Quorum.ANY, [vacant.pk])]), lazy_resolution=True)
    process = _start()

    engine.cancel(process_id=process.pk)

    assert process.stages.get(order=1).state == StageState.SKIPPED
    assert process.pk not in engine.pending_no_executor_process_ids()


def test_retry_endpoint_answers_with_the_card():
    vacant = make_user("vacant-holder")
    Employee.objects.filter(user_id=vacant.pk).update(is_deleted=True)
    _flag(make_route([(1, "Первый", Quorum.ANY, [vacant.pk])]), lazy_resolution=True)
    process = _start()
    _acting(vacant, make_user("acting"))

    resp = post_json(Client(), f"{BASE}/processes/{process.pk}/retry-executors", {},
                     **auth(admin_token()))

    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert body["found"] == 1
    assert body["process"]["stages"][0]["state"] == StageState.ACTIVE


def test_periodic_dispatch_retries_in_public_before_any_company():
    from apps.signoff import tasks

    vacant = make_user("vacant-holder")
    Employee.objects.filter(user_id=vacant.pk).update(is_deleted=True)
    _flag(make_route([(1, "Первый", Quorum.ANY, [vacant.pk])]), lazy_resolution=True)
    process = _start()
    _acting(vacant, make_user("acting"))

    assert tasks.retry_no_executor_dispatch() == {"public": {"processes": 1, "found": 1}}
    assert process.stages.get(order=1).state == StageState.ACTIVE


# ── ручки маршрута ──────────────────────────────────────────────────────

def test_route_endpoints_take_and_return_the_flags():
    gd, fd = make_user("gd"), make_user("fd")
    created = post_json(Client(), f"{BASE}/routes", {
        "subject_type": SUBJECT, "name": "БЗО", "forbid_self_approval": True,
        "reject_comment_min": 10, "lazy_resolution": True,
        "no_executor_notify_position_ids": [gd.pk, gd.pk],
        "escalation_position_id": gd.pk, "self_skip_notify_position_ids": [fd.pk],
    }, **auth(admin_token()))
    assert created.status_code == 201, created.content
    body = created.json()
    assert body["no_executor_notify_position_ids"] == [gd.pk]  # без дублей
    assert body["escalation_position"]["title"] == f"Signoff {gd.username}"
    assert body["reject_comment_min"] == 10 and body["lazy_resolution"] is True

    renamed = patch_json(Client(), f"{BASE}/routes/{body['id']}", {"name": "БЗО-2"},
                         **auth(admin_token()))
    assert renamed.json()["escalation_position_id"] == gd.pk  # не стёрт патчем имени
    cleared = patch_json(Client(), f"{BASE}/routes/{body['id']}",
                         {"escalation_position_id": None}, **auth(admin_token()))
    assert cleared.json()["escalation_position_id"] is None


def test_unknown_position_in_flags_is_a_conflict():
    resp = post_json(Client(), f"{BASE}/routes", {
        "subject_type": SUBJECT, "name": "БЗО", "escalation_position_id": 987654,
    }, **auth(admin_token()))
    assert resp.status_code == 409
    assert "987654" in resp.json()["detail"]
