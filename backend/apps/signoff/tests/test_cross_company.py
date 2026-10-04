"""Согласование между компаниями (мастер-план БЗО, B8.1).

Две настоящие схемы (``two_company_schemas``): ``alpha`` — холдинг,
``beta`` — его дочерняя. Директора — в штате холдинга; документ, маршрут,
процесс и задачи — в схеме дочерней. Проверяется то, ради чего B8.1:

* этап маршрута дочерней стоит на должности холдинга, а должность компании
  не из дерева взять нельзя;
* держатель (и временный исполнитель) должности холдинга получает задачу в
  дочерней; недоступный холдинг — отказ на запуске или «Нет исполнителя»;
* один человек на двух должностях этапа — одна задача на обе;
* единая очередь «Ждёт меня» и решение прямо из холдинга со всеми отказами.
"""

from __future__ import annotations

import dataclasses
import itertools
from datetime import date
from types import SimpleNamespace

import pytest
from django.core.cache import cache

from apps.companies.models import Company, CompanyKind, CompanyModule, CompanyStatus
from apps.hr.models import ActingAssignment, Department, Employee, EmployeeStatus, Position
from apps.signoff.models import (
    ApprovalEvent,
    ApprovalRouteStageRole,
    ApprovalTask,
    ProcessState,
    Quorum,
    StageState,
    TaskState,
)
from apps.signoff.services import engine, registry, route_service
from apps.signoff.tests.helpers import BASE, SUBJECT, auth, make_doc, post_json, token
from apps.signoff.tests.testapp import hooks
from apps.users.models import User, UserStatus
from htqweb.tenancy.db import use_company

pytestmark = pytest.mark.django_db

_WEIGHTS = itertools.count(50_001)


@pytest.fixture
def group(two_company_schemas):
    holding, child = two_company_schemas
    Company.objects.filter(slug=holding).update(kind=CompanyKind.HOLDING)
    row = Company.objects.get(slug=child)
    row.parent = Company.objects.get(slug=holding)
    row.save(update_fields=["parent"])
    cache.clear()
    hooks.reset()
    return SimpleNamespace(holding=holding, child=child)


def person(username: str) -> User:
    return User.objects.create(username=username, email=f"{username}@htq.test",
                               password="x", status=UserStatus.ACTIVE)


def position(company: str, title: str, *holders: User) -> int:
    """Должность в штате ``company`` и её держатели."""
    with use_company(company):
        department, _ = Department.objects.get_or_create(
            path="b81", defaults={"name": "B8.1"})
        pos = Position.objects.create(title=title, department=department,
                                      weight=next(_WEIGHTS))
        for user in holders:
            Employee.objects.create(
                user_id=user.pk, first_name=user.username, last_name="Тестов",
                email=f"emp-{company}-{user.username}@htq.test", department=department,
                position=pos, hire_date="2024-01-01", status=EmployeeStatus.ACTIVE)
    return pos.pk


def child_route(group, refs, *, quorum=Quorum.ANY, **flags):
    """Маршрут пробного документа в дочерней: один этап на должностях ``refs``."""
    with use_company(group.child):
        route = route_service.create_route(subject_type=SUBJECT, name="Маршрут дочерней",
                                           **flags)
        route_service.add_stage(route.pk, order=1, name="Финансовый директор",
                                quorum=quorum, position_ids=[], positions=refs)
    return route


def start_in_child(group, *, author: User | None = None, **kwargs):
    with use_company(group.child):
        doc = make_doc()
        process = engine.start(subject_type=SUBJECT, subject_id=doc.pk,
                               initiator_id=author.pk if author else None, **kwargs)
    return doc, process


def holding_headers(group, user: User) -> dict:
    return {"HTTP_X_HTQ_COMPANY": group.holding,
            **auth(token(user_id=user.pk, sub=str(user.pk), company=group.holding))}


def cross_company_subject(**extra) -> None:
    """Пробный документ, который можно решать из вышестоящей компании (как у БЗО)."""
    registry._SUBJECTS[SUBJECT] = dataclasses.replace(
        registry.get_subject(SUBJECT), cross_company_decisions=True, **extra)


# ── маршрут ──────────────────────────────────────────────────────────────

def test_child_stage_stands_on_holding_position(group):
    fd = person("fd")
    fd_pos = position(group.holding, "Финансовый директор", fd)
    route = child_route(group, [{"company": group.holding, "position_id": fd_pos}])

    with use_company(group.child):
        roles = list(ApprovalRouteStageRole.objects.filter(stage__route=route)
                     .values_list("position_company", "position_id"))
        card = route_service.serialize_route(route_service.get_route_or_404(route.pk))

    assert roles == [(group.holding, fd_pos)]
    role = card["stages"][0]["roles"][0]
    assert role["company"] == group.holding
    assert role["company_name"] == group.holding  # название компании в фикстуре = слаг
    assert role["title"] == "Финансовый директор"


def test_own_company_named_by_slug_is_stored_as_own(group):
    """Своя компания, присланная слагом, хранится пустой строкой — иначе одна
    должность разошлась бы на две по уникальности и кворуму."""
    director = person("dir")
    own_pos = position(group.child, "Директор", director)
    route = child_route(group, [{"company": group.child, "position_id": own_pos}])
    with use_company(group.child):
        assert list(ApprovalRouteStageRole.objects.filter(stage__route=route)
                    .values_list("position_company", flat=True)) == [""]


def test_position_only_from_own_and_upper_companies(group):
    director = person("dir")
    child_pos = position(group.child, "Директор", director)
    with use_company(group.holding):
        route = route_service.create_route(subject_type=SUBJECT, name="Маршрут холдинга")
        with pytest.raises(route_service.RouteConflict, match="не вышестоящая"):
            route_service.add_stage(
                route.pk, order=1, name="Директор дочерней", quorum=Quorum.ANY,
                position_ids=[], positions=[{"company": group.child, "position_id": child_pos}])


def test_unknown_holding_position_is_refused_on_setup(group):
    with use_company(group.child):
        route = route_service.create_route(subject_type=SUBJECT, name="Маршрут дочерней")
        with pytest.raises(route_service.RouteConflict, match="Не найдены должности в компании"):
            route_service.add_stage(
                route.pk, order=1, name="ФД", quorum=Quorum.ANY, position_ids=[],
                positions=[{"company": group.holding, "position_id": 987_654}])


def test_direct_decisions_flag_needs_a_cross_company_subject(group):
    route = child_route(group, [{"company": group.holding,
                                 "position_id": position(group.holding, "ФД", person("fd"))}])
    with use_company(group.child):
        with pytest.raises(route_service.RouteConflict, match="адресе своей компании"):
            route_service.update_route(route.pk, allow_direct_decisions=True)
        cross_company_subject()
        assert route_service.update_route(route.pk, allow_direct_decisions=True) \
            .allow_direct_decisions is True


# ── исполнители ─────────────────────────────────────────────────────────

def test_holding_holder_gets_the_task_in_child(group):
    fd, author = person("fd"), person("author")
    fd_pos = position(group.holding, "Финансовый директор", fd)
    child_route(group, [{"company": group.holding, "position_id": fd_pos}])

    doc, process = start_in_child(group, author=author)

    with use_company(group.child):
        task = ApprovalTask.objects.get(stage__process=process)
        assert (task.user_id, task.position_id, task.position_company) == \
            (fd.pk, fd_pos, group.holding)
        stage = process.stages.get()
        assert stage.role_refs == [{"company": group.holding, "position_id": fd_pos}]
        assert stage.role_ids == []  # своих должностей у этапа нет

        engine.act(task_id=task.pk, actor_id=fd.pk, decision=engine.APPROVE)
        process.refresh_from_db()
    assert process.state == ProcessState.APPROVED
    assert ("approved", doc.pk) in hooks.CALLS


def test_acting_holder_of_holding_position_gets_the_task(group):
    deputy = person("deputy")
    position(group.holding, "Заместитель ФД", deputy)
    fd_pos = position(group.holding, "Финансовый директор")  # держателя нет
    with use_company(group.holding):
        ActingAssignment.objects.create(
            position_id=fd_pos, employee=Employee.objects.get(user_id=deputy.pk),
            date_from=date.today(), date_to=date.today(), basis="Приказ №1")
    child_route(group, [{"company": group.holding, "position_id": fd_pos}])

    _, process = start_in_child(group)

    with use_company(group.child):
        assert list(ApprovalTask.objects.filter(stage__process=process)
                    .values_list("user_id", flat=True)) == [deputy.pk]


def test_archived_holding_refuses_start_without_lazy_resolution(group):
    fd_pos = position(group.holding, "Финансовый директор", person("fd"))
    child_route(group, [{"company": group.holding, "position_id": fd_pos}])
    Company.objects.filter(slug=group.holding).update(status=CompanyStatus.ARCHIVED)
    cache.clear()

    with pytest.raises(engine.RouteUnusable, match="в архиве"):
        start_in_child(group)


def test_archived_holding_is_no_executor_with_lazy_resolution(group):
    fd_pos = position(group.holding, "Финансовый директор", person("fd"))
    child_route(group, [{"company": group.holding, "position_id": fd_pos}],
                lazy_resolution=True)
    Company.objects.filter(slug=group.holding).update(status=CompanyStatus.ARCHIVED)
    cache.clear()

    _, process = start_in_child(group)

    with use_company(group.child):
        assert process.stages.get().state == StageState.NO_EXECUTOR
        event = ApprovalEvent.objects.get(process=process, kind="no_executor")
    assert event.payload["positions"] == [{"company": group.holding, "position_id": fd_pos}]
    assert "в архиве" in event.payload["unavailable"][group.holding]


def test_escalation_goes_to_holding_position(group):
    """Автор — единственный держатель должности дочерней; запрет
    самосогласования уводит группу на ГД холдинга."""
    author, gd = person("author"), person("gd")
    director_pos = position(group.child, "Директор", author)
    gd_pos = position(group.holding, "Генеральный директор", gd)
    child_route(group, [{"company": "", "position_id": director_pos}],
                forbid_self_approval=True, escalation_position_id=gd_pos,
                escalation_position_company=group.holding)

    _, process = start_in_child(group, author=author)

    with use_company(group.child):
        task = ApprovalTask.objects.get(stage__process=process)
        event = ApprovalEvent.objects.get(process=process, kind="self_approval_escalated")
    # Группа кворума — должность дочерней, решает ГД холдинга.
    assert (task.user_id, task.position_id, task.position_company) == (gd.pk, director_pos, "")
    assert event.payload["escalation_position_company"] == group.holding


def test_preapproved_holding_position_closes_its_stage(group):
    fd = person("fd")
    fd_pos = position(group.holding, "Финансовый директор", fd)
    child_route(group, [{"company": group.holding, "position_id": fd_pos}])

    _, process = start_in_child(group, preapproved=[
        {"position_id": fd_pos, "company": group.holding, "actor_id": fd.pk,
         "label": "Выбрано голосованием"}])

    with use_company(group.child):
        process.refresh_from_db()
        assert not ApprovalTask.objects.filter(stage__process=process).exists()
    assert process.state == ProcessState.APPROVED
    assert process.preapproved[0]["company"] == group.holding


# ── один человек на двух должностях ──────────────────────────────────────

def test_two_positions_of_one_person_make_one_task(group):
    """ГД холдинга исполняет и должность дочерней: задача одна, решение — за обе
    (раньше — вторая задача тому же человеку и 500 на уникальности)."""
    boss = person("boss")
    child_pos = position(group.child, "Директор", boss)
    holding_pos = position(group.holding, "Генеральный директор", boss)
    child_route(group, [{"company": "", "position_id": child_pos},
                        {"company": group.holding, "position_id": holding_pos}],
                quorum=Quorum.ALL)

    _, process = start_in_child(group)

    with use_company(group.child):
        task = ApprovalTask.objects.get(stage__process=process)
        assert task.user_id == boss.pk
        assert task.also_positions == [{"company": group.holding, "position_id": holding_pos}]
        engine.act(task_id=task.pk, actor_id=boss.pk, decision=engine.APPROVE)
        process.refresh_from_db()
    assert process.state == ProcessState.APPROVED


def test_task_covering_two_positions_is_not_skipped_while_one_is_open(group):
    """Кворум «любой»: другой держатель закрыл первую должность — задача
    человека, который ещё нужен за вторую, не гасится."""
    other, boss = person("other"), person("boss")
    child_pos = position(group.child, "Директор", boss, other)
    holding_pos = position(group.holding, "Генеральный директор", boss)
    child_route(group, [{"company": "", "position_id": child_pos},
                        {"company": group.holding, "position_id": holding_pos}],
                quorum=Quorum.ANY)

    _, process = start_in_child(group)

    with use_company(group.child):
        other_task = ApprovalTask.objects.get(stage__process=process, user_id=other.pk)
        engine.act(task_id=other_task.pk, actor_id=other.pk, decision=engine.APPROVE)
        boss_task = ApprovalTask.objects.get(stage__process=process, user_id=boss.pk)
        assert boss_task.state == TaskState.PENDING
        process.refresh_from_db()
        assert process.state == ProcessState.PENDING

        engine.act(task_id=boss_task.pk, actor_id=boss.pk, decision=engine.APPROVE)
        process.refresh_from_db()
    assert process.state == ProcessState.APPROVED


# ── единая очередь и решение из холдинга ─────────────────────────────────

def _child_task(group, *, quorum=Quorum.ANY, stage_extra=None, **flags):
    fd, author = person("fd"), person("author")
    fd_pos = position(group.holding, "Финансовый директор", fd)
    route = child_route(group, [{"company": group.holding, "position_id": fd_pos}],
                        quorum=quorum, **flags)
    if stage_extra:
        with use_company(group.child):
            route.stages.update(**stage_extra)
    doc, process = start_in_child(group, author=author)
    with use_company(group.child):
        task = ApprovalTask.objects.get(stage__process=process)
    return SimpleNamespace(fd=fd, author=author, route=route, doc=doc, process=process,
                           task=task)


def test_inbox_all_shows_child_task_in_holding(client, group):
    case = _child_task(group)

    rows = client.get(f"{BASE}/tasks/mine/all", **holding_headers(group, case.fd)).json()

    assert [row["task_id"] for row in rows] == [case.task.pk]
    row = rows[0]
    assert row["company"]["slug"] == group.child
    assert row["can_enter"] is False  # членства в дочерней нет — это A8.1
    assert row["direct_allowed"] is False
    assert "адресе своей компании" in row["direct_blocker"]
    # Очередь текущей компании (холдинга) по-прежнему пуста.
    assert client.get(f"{BASE}/tasks/mine", **holding_headers(group, case.fd)).json() == []


def test_inbox_all_marks_direct_decision_when_route_allows(client, group):
    cross_company_subject()
    case = _child_task(group, allow_direct_decisions=True)

    row = client.get(f"{BASE}/tasks/mine/all", **holding_headers(group, case.fd)).json()[0]

    assert row["direct_allowed"] is True
    assert row["direct_blocker"] is None


def test_direct_decision_from_holding(client, group):
    cross_company_subject()
    case = _child_task(group, allow_direct_decisions=True)

    resp = post_json(client, f"{BASE}/companies/{group.child}/tasks/{case.task.pk}/decision",
                     {"decision": "approve"}, **holding_headers(group, case.fd))

    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert body["state"] == ProcessState.APPROVED
    assert body["company"]["slug"] == group.child
    with use_company(group.child):
        event = ApprovalEvent.objects.get(process=case.process, kind="task_approved")
    assert event.payload["decided_from"] == group.holding
    assert ("approved", case.doc.pk) in hooks.CALLS


def test_direct_decision_needs_the_route_flag(client, group):
    cross_company_subject()
    case = _child_task(group)  # флаг не включён

    resp = post_json(client, f"{BASE}/companies/{group.child}/tasks/{case.task.pk}/decision",
                     {"decision": "approve"}, **holding_headers(group, case.fd))

    assert resp.status_code == 403
    assert "не включено" in resp.json()["detail"]


def test_direct_decision_only_into_a_lower_company(client, group):
    cross_company_subject()
    case = _child_task(group, allow_direct_decisions=True)
    child_headers = {"HTTP_X_HTQ_COMPANY": group.child,
                     **auth(token(user_id=case.fd.pk, sub=str(case.fd.pk), company=group.child))}

    # Из дочерней — в холдинг (выше) и в саму себя: компании «нет».
    for slug in (group.holding, group.child):
        resp = post_json(client, f"{BASE}/companies/{slug}/tasks/{case.task.pk}/decision",
                         {"decision": "approve"}, **child_headers)
        assert resp.status_code == 404


def test_direct_decision_only_on_own_task(client, group):
    cross_company_subject()
    case = _child_task(group, allow_direct_decisions=True)
    stranger = person("stranger")

    resp = post_json(client, f"{BASE}/companies/{group.child}/tasks/{case.task.pk}/decision",
                     {"decision": "approve"}, **holding_headers(group, stranger))

    assert resp.status_code == 404


def test_direct_decision_blocked_by_attachment_stage(client, group):
    cross_company_subject()
    case = _child_task(group, allow_direct_decisions=True,
                       stage_extra={"requires_attachment": True})

    row = client.get(f"{BASE}/tasks/mine/all", **holding_headers(group, case.fd)).json()[0]
    resp = post_json(client, f"{BASE}/companies/{group.child}/tasks/{case.task.pk}/decision",
                     {"decision": "approve"}, **holding_headers(group, case.fd))

    assert row["direct_allowed"] is False and "приложить документ" in row["direct_blocker"]
    assert resp.status_code == 409
    assert "приложить документ" in resp.json()["detail"]


def test_direct_decision_blocked_by_option_vote(client, group):
    cross_company_subject()
    case = _child_task(group, allow_direct_decisions=True, stage_extra={"votes_option": True})
    hooks.OPTIONS[case.doc.pk] = [{"key": "original", "label": "Исходный"},
                                  {"key": "alt", "label": "Альтернатива"}]

    resp = post_json(client, f"{BASE}/companies/{group.child}/tasks/{case.task.pk}/decision",
                     {"decision": "approve", "option_key": "alt"},
                     **holding_headers(group, case.fd))

    assert resp.status_code == 409
    assert "выбрать вариант" in resp.json()["detail"]


def test_direct_decision_answers_503_when_signoff_is_off_in_child(client, group):
    cross_company_subject()
    case = _child_task(group, allow_direct_decisions=True)
    CompanyModule.objects.create(company=Company.objects.get(slug=group.child),
                                 app_label="signoff", enabled=False)
    cache.clear()

    resp = post_json(client, f"{BASE}/companies/{group.child}/tasks/{case.task.pk}/decision",
                     {"decision": "approve"}, **holding_headers(group, case.fd))

    assert resp.status_code == 503
    assert resp.json()["service"] == "signoff"


def test_direct_reject_keeps_the_comment_minimum(client, group):
    cross_company_subject()
    case = _child_task(group, allow_direct_decisions=True, reject_comment_min=10)

    resp = post_json(client, f"{BASE}/companies/{group.child}/tasks/{case.task.pk}/decision",
                     {"decision": "reject", "comment": "нет"}, **holding_headers(group, case.fd))

    assert resp.status_code == 422


def test_foreign_card_shows_summary_to_participant_only(client, group):
    cross_company_subject(summary=lambda subject_id: {
        "fields": [{"label": "Сумма", "value": "1 000 ₸"}],
        "lines": {"columns": [{"key": "name", "label": "Позиция"}],
                  "rows": [{"name": "Цемент"}], "total": None}})
    case = _child_task(group, allow_direct_decisions=True)
    path = f"{BASE}/companies/{group.child}/processes/{case.process.pk}"

    card = client.get(path, **holding_headers(group, case.fd)).json()
    stranger = client.get(path, **holding_headers(group, person("stranger")))

    assert card["summary"]["fields"] == [{"label": "Сумма", "value": "1 000 ₸"}]
    assert card["summary"]["lines"]["rows"] == [{"name": "Цемент"}]
    assert card["my_task_id"] == case.task.pk and card["direct_allowed"] is True
    assert card["stages"][0]["tasks"][0]["position_label"] == \
        f"Финансовый директор · {group.holding}"
    assert stranger.status_code == 404


# ── справочник должностей для редактора ─────────────────────────────────

def test_positions_directory_offers_own_and_upper_companies(client, group):
    fd_pos = position(group.holding, "Финансовый директор", person("fd"))
    admin = {"HTTP_X_HTQ_COMPANY": group.child,
             **auth(token(user_id=9, sub="9", is_admin=True, company=group.child))}

    companies = client.get(f"{BASE}/positions/companies", **admin).json()
    holding_positions = client.get(f"{BASE}/positions?company={group.holding}", **admin).json()
    from_holding = client.get(
        f"{BASE}/positions?company={group.child}",
        **{"HTTP_X_HTQ_COMPANY": group.holding,
           **auth(token(user_id=9, sub="9", is_admin=True, company=group.holding))})

    assert [(row["slug"], row["own"]) for row in companies] == \
        [(group.child, True), (group.holding, False)]
    assert [row["id"] for row in holding_positions] == [fd_pos]
    assert from_holding.status_code == 404  # дочерняя для холдинга не вышестоящая
