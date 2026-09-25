"""Область маршрута, согласующие «поимённо» и «назначает объект», хук событий.

Три расширения движка ради конструктора форм («Запросы»), но проверяются
на нейтральной модели ``testapp.ProbeDoc`` — движок по-прежнему не знает ни
про шаблоны, ни про заявки:

* маршрут в области (``ApprovalRoute.scope``) берётся по ``Subject.scope_of``
  объекта, а маршрут «на весь тип» (``scope=""``) как жил, так и живёт;
* ``ApproverKind.USERS`` — люди из маршрута; ``ApproverKind.SUBJECT`` — те,
  кого назвал объект по ключу из ``approver_fields``;
* ``Subject.on_event`` получает события после коммита и не роняет процесс.
"""

from __future__ import annotations

import pytest
from django.test import Client

from apps.signoff.models import (
    ApprovalProcess,
    ApprovalRoute,
    ApprovalRouteStage,
    ApproverKind,
    ProcessState,
    Quorum,
)
from apps.signoff import interface
from apps.signoff.services import engine, registry
from apps.signoff.services import route_service as routes
from apps.signoff.tests.helpers import (
    BASE, admin_token, auth, make_doc, make_route, make_user, patch_json,
    post_json, task_for, user_token,
)
from apps.signoff.tests.testapp import hooks

pytestmark = pytest.mark.django_db

SUBJECT = "testapp.probedoc"


@pytest.fixture(autouse=True)
def _reset():
    hooks.reset()
    yield
    hooks.reset()


def _users_stage(order: int, name: str, *user_ids: int, quorum=Quorum.ALL):
    return (order, name, quorum, [], {"approver_kind": ApproverKind.USERS,
                                      "user_ids": list(user_ids)})


# ═══════════════════════════════════════════════════════════════════════
# Область маршрута
# ═══════════════════════════════════════════════════════════════════════

def test_scope_route_is_picked_by_the_objects_scope():
    """Объект области «strict» идёт по своему маршруту, обычный — по общему."""
    plain, strict = make_user("plain"), make_user("strict")
    make_route([_users_stage(1, "Общий", plain.pk)])
    make_route([_users_stage(1, "Строгий", strict.pk)], name="Строгий", scope="strict")

    common = engine.start(subject_type=SUBJECT, subject_id=make_doc().pk,
                          initiator_id=plain.pk)
    special = engine.start(subject_type=SUBJECT,
                           subject_id=make_doc(scope="strict").pk,
                           initiator_id=plain.pk)

    assert common.scope == "" and [t.user_id for t in common.stages.first().tasks.all()] == [plain.pk]
    assert special.scope == "strict"
    assert [t.user_id for t in special.stages.first().tasks.all()] == [strict.pk]


def test_missing_scope_route_names_the_scope():
    make_route([_users_stage(1, "Общий", make_user("p").pk)])
    with pytest.raises(engine.RouteNotConfigured, match="Строгие"):
        engine.start(subject_type=SUBJECT, subject_id=make_doc(scope="strict").pk,
                     initiator_id=1)


def test_one_active_route_per_scope_but_different_scopes_coexist():
    ApprovalRoute.objects.create(subject_type=SUBJECT, name="a")
    ApprovalRoute.objects.create(subject_type=SUBJECT, name="b", scope="strict")
    with pytest.raises(routes.RouteConflict, match="активный маршрут"):
        routes.create_route(subject_type=SUBJECT, name="c", scope="strict")
    # Тип без областей маршрута по области не получит.
    registry.register_subject(SUBJECT, label="x", model=hooks.ProbeDoc)
    with pytest.raises(routes.RouteConflict, match="не делится на области"):
        routes.create_route(subject_type=SUBJECT, name="d", scope="strict")


def test_fact_fields_are_asked_per_scope():
    assert {f["key"] for f in registry.fields_for(SUBJECT)} == {"zone", "amount", "urgent"}
    assert "audited" in {f["key"] for f in registry.fields_for(SUBJECT, "strict")}
    # Условие по факту области принимается только в маршруте этой области.
    strict = routes.create_route(subject_type=SUBJECT, name="s", scope="strict")
    plain = routes.create_route(subject_type=SUBJECT, name="p")
    owner = make_user("owner")
    condition = [{"field": "audited", "op": "eq", "value": True}]
    routes.add_stage(strict.pk, order=1, name="Аудит", quorum=Quorum.ALL,
                     position_ids=[owner.pk], condition=condition)
    with pytest.raises(routes.RouteConflict):
        routes.add_stage(plain.pk, order=1, name="Аудит", quorum=Quorum.ALL,
                         position_ids=[owner.pk], condition=condition)


def test_interface_has_active_route_and_start_respect_scope():
    make_route([_users_stage(1, "Общий", make_user("p").pk)])
    assert interface.has_active_route(SUBJECT) is True
    assert interface.has_active_route(SUBJECT, "strict") is False
    card = interface.start_process(subject_type=SUBJECT,
                                   subject_id=make_doc(scope="strict").pk,
                                   initiator_id=1, scope="")
    assert card["scope"] == ""  # явная область перебивает область объекта


def test_route_api_exposes_scope_and_schema_of_the_scope(client):
    admin = auth(admin_token())
    created = post_json(client, f"{BASE}/routes",
                        {"subject_type": SUBJECT, "name": "Строгий", "scope": "strict"},
                        **admin)
    assert created.status_code == 201, created.content
    assert created.json()["scope"] == "strict"
    assert created.json()["scope_label"] == "Строгие"

    card = client.get(f"{BASE}/routes/{created.json()['id']}", **admin).json()
    assert "audited" in {f["key"] for f in card["fields"]}
    assert card["approver_fields"] == [{"key": "owner", "label": "Владелец документа"}]

    subjects = client.get(f"{BASE}/subjects", **auth(admin_token())).json()
    probe = next(row for row in subjects if row["subject_type"] == SUBJECT)
    assert probe["scopes"] == [{"scope": "strict", "label": "Строгие",
                                "has_active_route": True}]
    assert probe["has_active_route"] is False  # общий маршрут не заведён

    listed = client.get(f"{BASE}/routes?scope=strict", **admin).json()
    assert [row["scope"] for row in listed] == ["strict"]


# ═══════════════════════════════════════════════════════════════════════
# Согласующие поимённо
# ═══════════════════════════════════════════════════════════════════════

def test_users_stage_addresses_the_named_people_and_settles_by_quorum():
    a, b, author = make_user("a"), make_user("b"), make_user("author")
    make_route([_users_stage(1, "Двое", a.pk, b.pk, quorum=Quorum.ANY)])
    doc = make_doc()
    process = engine.start(subject_type=SUBJECT, subject_id=doc.pk, initiator_id=author.pk)

    stage = process.stages.get()
    assert stage.approver_kind == ApproverKind.USERS
    assert stage.user_ids == [a.pk, b.pk] and stage.role_ids == []
    assert sorted(t.user_id for t in stage.tasks.all()) == sorted([a.pk, b.pk])

    engine.act(task_id=task_for(process, a.pk).pk, actor_id=a.pk, decision=engine.APPROVE)
    process.refresh_from_db()
    assert process.state == ProcessState.APPROVED
    doc.refresh_from_db()
    assert doc.published is True


def test_users_stage_with_a_left_person_refuses_to_start():
    gone = make_user("gone", active=False)
    make_route([_users_stage(1, "Ушедший", gone.pk)])
    with pytest.raises(engine.RouteUnusable, match="неактивный"):
        engine.start(subject_type=SUBJECT, subject_id=make_doc().pk, initiator_id=1)


def test_users_stage_is_configured_over_the_api(client):
    a, gone = make_user("a"), make_user("gone", active=False)
    admin = auth(admin_token())
    route_id = post_json(client, f"{BASE}/routes",
                         {"subject_type": SUBJECT, "name": "Люди"}, **admin).json()["id"]

    ok = post_json(client, f"{BASE}/routes/{route_id}/stages",
                   {"order": 1, "name": "Люди", "approver_kind": "users",
                    "user_ids": [a.pk]}, **admin)
    assert ok.status_code == 201, ok.content
    (person,) = ok.json()["users"]
    assert person["user_id"] == a.pk and person["full_name"] and person["is_active"] is True
    assert ok.json()["roles"] == []

    # Неактивный — 409 на настройке, а не на отправке.
    bad = post_json(client, f"{BASE}/routes/{route_id}/stages",
                    {"order": 2, "name": "Ушедший", "approver_kind": "users",
                     "user_ids": [gone.pk]}, **admin)
    assert bad.status_code == 409 and str(gone.pk) in bad.json()["detail"]

    # Должности у этапа «поимённо» — противоречие.
    mixed = post_json(client, f"{BASE}/routes/{route_id}/stages",
                      {"order": 2, "name": "Смесь", "approver_kind": "users",
                       "user_ids": [a.pk], "position_ids": [a.pk]}, **admin)
    assert mixed.status_code == 422

    # Смена вида на «по должности» без списка — 409; с должностью — люди стёрты.
    stage_id = ok.json()["id"]
    assert patch_json(client, f"{BASE}/stages/{stage_id}",
                      {"approver_kind": "position"}, **admin).status_code == 409
    switched = patch_json(client, f"{BASE}/stages/{stage_id}",
                          {"approver_kind": "position", "position_ids": [a.pk]}, **admin)
    assert switched.status_code == 200, switched.content
    assert switched.json()["user_ids"] == [] and [r["position_id"] for r in switched.json()["roles"]] == [a.pk]


# ═══════════════════════════════════════════════════════════════════════
# Согласующих называет объект
# ═══════════════════════════════════════════════════════════════════════

def test_subject_stage_asks_the_object_for_its_approvers():
    owner, author = make_user("owner"), make_user("author")
    make_route([(1, "Владелец", Quorum.ALL, [],
                 {"approver_kind": ApproverKind.SUBJECT, "approver_key": "owner"})])
    doc = make_doc(owner_id=owner.pk)

    process = engine.start(subject_type=SUBJECT, subject_id=doc.pk, initiator_id=author.pk)
    stage = process.stages.get()
    assert stage.approver_kind == ApproverKind.SUBJECT and stage.approver_key == "owner"
    assert [t.user_id for t in stage.tasks.all()] == [owner.pk]


def test_subject_stage_refuses_when_the_object_names_nobody():
    make_route([(1, "Владелец", Quorum.ALL, [],
                 {"approver_kind": ApproverKind.SUBJECT, "approver_key": "owner"})])
    with pytest.raises(engine.RouteUnusable, match="не назвал"):
        engine.start(subject_type=SUBJECT, subject_id=make_doc().pk, initiator_id=1)


def test_subject_stage_key_is_validated_against_the_registry(client):
    admin = auth(admin_token())
    route_id = post_json(client, f"{BASE}/routes",
                         {"subject_type": SUBJECT, "name": "Объект"}, **admin).json()["id"]
    bad = post_json(client, f"{BASE}/routes/{route_id}/stages",
                    {"order": 1, "name": "Кто-то", "approver_kind": "subject",
                     "approver_key": "nobody"}, **admin)
    assert bad.status_code == 409 and "owner" in bad.json()["detail"]
    ok = post_json(client, f"{BASE}/routes/{route_id}/stages",
                   {"order": 1, "name": "Владелец", "approver_kind": "subject",
                    "approver_key": "owner"}, **admin)
    assert ok.status_code == 201, ok.content
    assert ok.json()["approver_label"] == "Владелец документа"


# ═══════════════════════════════════════════════════════════════════════
# События и вкладки реестра
# ═══════════════════════════════════════════════════════════════════════

def test_on_event_reports_activation_decisions_and_the_outcome(
        client, django_capture_on_commit_callbacks):
    a, author = make_user("a"), make_user("author")
    make_route([_users_stage(1, "Один", a.pk)])
    doc = make_doc()
    # События уходят ПОСЛЕ коммита: тест живёт в транзакции, поэтому
    # on_commit-колбэки исполняются явно.
    with django_capture_on_commit_callbacks(execute=True):
        started = post_json(client, f"{BASE}/processes",
                            {"subject_type": SUBJECT, "subject_id": doc.pk,
                             "initiator_id": author.pk}, **auth(admin_token()))
    assert started.status_code == 201, started.content
    task = task_for(ApprovalProcess.objects.get(pk=started.json()["id"]), a.pk)
    with django_capture_on_commit_callbacks(execute=True):
        decided = post_json(client, f"{BASE}/tasks/{task.pk}/decision",
                            {"decision": "approve"}, **auth(user_token(a)))
    assert decided.status_code == 200, decided.content

    kinds = [kind for _, kind, _ in hooks.EVENTS]
    assert kinds == ["stage_activated", "task_decided", "approved"]
    activated = hooks.EVENTS[0][2]
    assert activated["user_ids"] == [a.pk] and activated["process_id"] == started.json()["id"]
    assert hooks.EVENTS[1][2]["decision"] == "approve"


def test_interface_lists_awaiting_and_decided_subject_ids():
    a, b = make_user("a"), make_user("b")
    make_route([_users_stage(1, "Двое", a.pk, b.pk)])
    first, second = make_doc("first"), make_doc("second")
    p1 = engine.start(subject_type=SUBJECT, subject_id=first.pk, initiator_id=b.pk)
    engine.start(subject_type=SUBJECT, subject_id=second.pk, initiator_id=b.pk)

    assert interface.list_awaiting_subject_ids(a.pk, SUBJECT) == [second.pk, first.pk]
    engine.act(task_id=task_for(p1, a.pk).pk, actor_id=a.pk, decision=engine.APPROVE)
    assert interface.list_awaiting_subject_ids(a.pk, SUBJECT) == [second.pk]
    assert interface.list_decided_subject_ids(a.pk, SUBJECT) == [first.pk]
    assert interface.list_decided_subject_ids(b.pk, SUBJECT) == []


def test_batch_decision_reports_per_task(client):
    a = make_user("a")
    make_route([_users_stage(1, "Один", a.pk)])
    p1 = engine.start(subject_type=SUBJECT, subject_id=make_doc().pk, initiator_id=1)
    p2 = engine.start(subject_type=SUBJECT, subject_id=make_doc().pk, initiator_id=1)
    t1, t2 = task_for(p1, a.pk), task_for(p2, a.pk)

    resp = post_json(client, f"{BASE}/tasks/batch-decision",
                     {"task_ids": [t1.pk, t2.pk, 999999], "decision": "approve"},
                     **auth(user_token(a)))
    assert resp.status_code == 200, resp.content
    assert [(row["task_id"], row["ok"]) for row in resp.json()] == [
        (t1.pk, True), (t2.pk, True), (999999, False)]
    assert ApprovalProcess.objects.filter(state=ProcessState.APPROVED).count() == 2


def test_contracts_style_route_without_scope_still_works_unchanged():
    """Регресс-страховка: маршрут по должностям без области — как раньше."""
    a = make_user("a")
    make_route([(1, "По должности", Quorum.ALL, [a.pk])])
    process = engine.start(subject_type=SUBJECT, subject_id=make_doc().pk, initiator_id=1)
    stage = process.stages.get()
    assert stage.approver_kind == ApproverKind.POSITION
    assert stage.role_ids == [a.pk] and stage.user_ids == [] and stage.approver_key == ""
    assert ApprovalRouteStage.objects.get().user_ids == []
