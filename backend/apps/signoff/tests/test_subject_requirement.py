"""Этап требует от ОБЪЕКТА результата — третий гейт рядом с документом и
пояснением.

Те два — про решение (что принёс согласующий); этот — про сам объект: на
нём должно быть что-то сделано, прежде чем этап закроется. Что именно и
сделано ли, движок не знает — спрашивает предметную аппку по ключу этапа
(``Subject.requirement_fields`` / ``check_requirement``) и отдаёт её
объяснение человеку как есть. Здесь тестовый тип требует «документ назван».
"""

import pytest
from django.test import Client

from apps.signoff import interface as signoff
from apps.signoff.models import (
    ApprovalRoute, ApprovalTask, Quorum, StageState, TaskState,
)
from apps.signoff.services import engine, route_service
from apps.signoff.services.route_service import RouteConflict

from .helpers import (
    BASE, admin_token, auth, make_doc, make_route, make_user, post_json,
    user_token,
)
from .testapp.hooks import REQUIREMENT_TITLED
from .testapp.models import ProbeDoc

pytestmark = pytest.mark.django_db

SUBJECT = ProbeDoc.SIGNOFF_SUBJECT_TYPE


@pytest.fixture
def client():
    return Client()


def active_task(process, user_id: int) -> ApprovalTask:
    return ApprovalTask.objects.get(stage__process=process, user_id=user_id,
                                    state=TaskState.PENDING,
                                    stage__state=StageState.ACTIVE)


def route_with_requirement(*user_ids: int) -> ApprovalRoute:
    return make_route([
        (1, "Рабочий шаг", Quorum.ALL, list(user_ids),
         {"requirement_key": REQUIREMENT_TITLED}),
    ])


# ── гейт на решении ───────────────────────────────────────────────────

def test_the_stage_refuses_to_close_until_the_subject_is_ready():
    a = make_user("a")
    route_with_requirement(a.pk)
    doc = make_doc(title="")
    process = engine.start(subject_type=SUBJECT, subject_id=doc.pk)

    with pytest.raises(engine.SubjectRequirementUnmet) as exc:
        engine.act(task_id=active_task(process, a.pk).pk, actor_id=a.pk,
                   decision=engine.APPROVE)
    # Отказ называет этап и повторяет объяснение аппки — человеку видно,
    # что именно сделать.
    assert "«Рабочий шаг»" in str(exc.value)
    assert "у документа нет названия" in str(exc.value)

    # Задача осталась открытой: отказ по требованию не записывает решения.
    assert active_task(process, a.pk).state == TaskState.PENDING

    ProbeDoc.objects.filter(pk=doc.pk).update(title="Назван")
    engine.act(task_id=active_task(process, a.pk).pk, actor_id=a.pk,
               decision=engine.APPROVE)
    process.refresh_from_db()
    assert process.state == "approved"


def test_reject_and_rework_do_not_need_the_requirement():
    """Требование — к согласованию. Отклонить или вернуть на доработку можно
    и с пустым объектом: ровно так и возвращают «заполните»."""
    a = make_user("a")
    route_with_requirement(a.pk)

    doc = make_doc(title="")
    process = engine.start(subject_type=SUBJECT, subject_id=doc.pk)
    engine.act(task_id=active_task(process, a.pk).pk, actor_id=a.pk,
               decision=engine.REWORK, comment="назовите документ")
    process.refresh_from_db()
    assert process.state == "rework"

    doc2 = make_doc(title="")
    process2 = engine.start(subject_type=SUBJECT, subject_id=doc2.pk)
    engine.act(task_id=active_task(process2, a.pk).pk, actor_id=a.pk,
               decision=engine.REJECT, comment="нет")
    process2.refresh_from_db()
    assert process2.state == "rejected"


def test_the_refusal_reaches_the_api_as_409(client):
    a = make_user("a")
    route_with_requirement(a.pk)
    doc = make_doc(title="")
    process = engine.start(subject_type=SUBJECT, subject_id=doc.pk)
    task = active_task(process, a.pk)
    resp = post_json(client, f"{BASE}/tasks/{task.pk}/decision",
                     {"decision": "approve", "comment": ""},
                     **auth(user_token(a)))
    assert resp.status_code == 409
    assert "у документа нет названия" in resp.json()["detail"]


# ── настройка ─────────────────────────────────────────────────────────

def test_an_unknown_requirement_is_refused_at_setup(client):
    route = make_route([(1, "Шаг", Quorum.ALL, [make_user("a").pk])])
    with pytest.raises(RouteConflict, match="неизвестно"):
        route_service.add_stage(route.pk, order=2, name="Ещё", quorum=Quorum.ALL,
                                position_ids=[make_user("b").pk],
                                requirement_key="no_such_thing")

    stage = route.stages.get()
    resp = client.patch(f"{BASE}/stages/{stage.pk}",
                        data='{"requirement_key": "no_such_thing"}',
                        content_type="application/json", **auth(admin_token()))
    assert resp.status_code == 409


def test_the_editor_learns_the_keys_and_the_stage_carries_a_label(client):
    a = make_user("a")
    route = route_with_requirement(a.pk)

    subjects = client.get(f"{BASE}/subjects", **auth(admin_token())).json()
    probe = next(row for row in subjects if row["subject_type"] == SUBJECT)
    assert probe["requirement_fields"] == [
        {"key": REQUIREMENT_TITLED, "label": "Документ назван"}]

    card = client.get(f"{BASE}/routes/{route.pk}", **auth(admin_token())).json()
    assert card["requirement_fields"] == [
        {"key": REQUIREMENT_TITLED, "label": "Документ назван"}]
    (stage,) = card["stages"]
    assert stage["requirement_key"] == REQUIREMENT_TITLED
    assert stage["requirement_label"] == "Документ назван"


def test_configure_route_carries_the_requirement():
    a = make_user("a")
    signoff.configure_route(subject_type=SUBJECT, name="Программно", stages=[
        {"order": 1, "name": "Шаг", "quorum": "all", "approver_kind": "users",
         "user_ids": [a.pk], "requirement_key": REQUIREMENT_TITLED},
    ])
    stage = ApprovalRoute.objects.get(name="Программно").stages.get()
    assert stage.requirement_key == REQUIREMENT_TITLED


# ── что видно людям ───────────────────────────────────────────────────

def test_the_inbox_and_the_process_card_name_the_requirement(client):
    a = make_user("a")
    route_with_requirement(a.pk)
    doc = make_doc(title="")
    process = engine.start(subject_type=SUBJECT, subject_id=doc.pk)

    (row,) = client.get(f"{BASE}/tasks/mine", **auth(user_token(a))).json()
    assert row["requirement_label"] == "Документ назван"

    card = client.get(f"{BASE}/processes/{process.pk}", **auth(user_token(a))).json()
    (stage,) = card["stages"]
    assert stage["requirement_key"] == REQUIREMENT_TITLED
    assert stage["requirement_label"] == "Документ назван"


def test_pending_requirement_keys_belong_to_the_active_approver_only():
    """Предметная аппка по этому списку решает, кому сейчас можно заполнять
    поля объекта: тому, чей рабочий шаг идёт, — не следующему и не
    закончившему."""
    a, b = make_user("a"), make_user("b")
    make_route([
        (1, "Рабочий шаг", Quorum.ALL, [a.pk], {"requirement_key": REQUIREMENT_TITLED}),
        (2, "Утверждение", Quorum.ALL, [b.pk]),
    ])
    doc = make_doc(title="")
    process = engine.start(subject_type=SUBJECT, subject_id=doc.pk)

    keys = lambda user: signoff.pending_requirement_keys(  # noqa: E731
        user_id=user.pk, subject_type=SUBJECT, subject_id=doc.pk)
    assert keys(a) == [REQUIREMENT_TITLED]
    assert keys(b) == []  # очередь до него не дошла

    ProbeDoc.objects.filter(pk=doc.pk).update(title="Назван")
    engine.act(task_id=active_task(process, a.pk).pk, actor_id=a.pk,
               decision=engine.APPROVE)
    assert keys(a) == []  # шаг закрыт
    assert keys(b) == []  # у этапа утверждения требований нет


def test_the_snapshot_keeps_the_requirement_of_a_running_process():
    """Снять требование с маршрута посреди согласования не должно отпускать
    тех, кто ещё не решил, — правила зафиксированы на запуске."""
    a = make_user("a")
    route = route_with_requirement(a.pk)
    doc = make_doc(title="")
    process = engine.start(subject_type=SUBJECT, subject_id=doc.pk)

    route_service.update_stage(route.stages.get().pk, requirement_key="")
    with pytest.raises(engine.SubjectRequirementUnmet):
        engine.act(task_id=active_task(process, a.pk).pk, actor_id=a.pk,
                   decision=engine.APPROVE)
