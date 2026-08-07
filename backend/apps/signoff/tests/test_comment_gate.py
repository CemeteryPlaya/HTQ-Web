"""Этап, который нельзя согласовать без пояснения (``requires_comment``).

Третье независимое поле «этапа подписи» рядом с ``approver_kind`` и
``requires_attachment`` — и проверяется теми же правилами, что документ:
гейт стоит только на СОГЛАСОВАНИИ, требование берётся из СНИМКА процесса, а не
из живого маршрута, и на HTTP-пути отказ приходит как 409. Раздельность полей
проверяется тем, что пояснение требуется и БЕЗ документа, и от НАЗВАННОГО
согласующего (не только от инициатора).
"""

from __future__ import annotations

import pytest

from apps.signoff.models import ProcessState, Quorum, TaskState
from apps.signoff.services import engine
from apps.signoff.tests.helpers import (
    BASE,
    admin_token,
    auth,
    make_doc,
    make_route,
    make_user,
    post_json,
    task_for,
    token,
    user_token,
)
from apps.signoff.tests.testapp import hooks
from apps.signoff.tests.testapp.models import ProbeDoc

pytestmark = pytest.mark.django_db

SUBJECT = ProbeDoc.SIGNOFF_SUBJECT_TYPE

# Пояснение требуется от НАЗВАННОГО согласующего и без документа — нарочно не
# «этап подписи»: так видно, что requires_comment не приклеен к инициатору.
NEEDS_COMMENT = {"requires_comment": True}


@pytest.fixture(autouse=True)
def _reset_calls():
    hooks.reset()
    yield
    hooks.reset()


def _decide(client, task_id: int, tok: str, decision="approve", comment=""):
    return post_json(client, f"{BASE}/tasks/{task_id}/decision",
                     {"decision": decision, "comment": comment}, **auth(tok))


# ═══════════════════════════════════════════════════════════════════════
# Гейт пояснения
# ═══════════════════════════════════════════════════════════════════════

def test_approving_without_a_comment_is_refused():
    a = make_user("a")
    doc = make_doc()
    make_route([(1, "Проверка", Quorum.ALL, [a.pk], NEEDS_COMMENT)])
    process = engine.start(subject_type=SUBJECT, subject_id=doc.pk,
                           initiator_id=a.pk)
    task = task_for(process, a.pk)

    with pytest.raises(engine.CommentRequired, match="пояснением"):
        engine.act(task_id=task.pk, actor_id=a.pk, decision="approve")

    # Отказ по гейту не оставляет за собой закрытую задачу.
    task.refresh_from_db()
    assert task.state == TaskState.PENDING
    process.refresh_from_db()
    assert process.state == ProcessState.PENDING


def test_a_whitespace_only_comment_does_not_count():
    """Пробел — не пояснение: гейт снимает ``strip()``, как и форма."""
    a = make_user("a")
    doc = make_doc()
    make_route([(1, "Проверка", Quorum.ALL, [a.pk], NEEDS_COMMENT)])
    process = engine.start(subject_type=SUBJECT, subject_id=doc.pk,
                           initiator_id=a.pk)

    with pytest.raises(engine.CommentRequired):
        engine.act(task_id=task_for(process, a.pk).pk, actor_id=a.pk,
                   decision="approve", comment="   \n\t ")


def test_approving_with_a_comment_passes():
    a = make_user("a")
    doc = make_doc()
    make_route([(1, "Проверка", Quorum.ALL, [a.pk], NEEDS_COMMENT)])
    process = engine.start(subject_type=SUBJECT, subject_id=doc.pk,
                           initiator_id=a.pk)

    engine.act(task_id=task_for(process, a.pk).pk, actor_id=a.pk,
               decision="approve", comment="Проверил, замечаний нет")

    process.refresh_from_db()
    assert process.state == ProcessState.APPROVED


def test_rejecting_without_a_comment_is_allowed():
    """Гейт стоит только на согласовании: у отказа комментарий и так по
    смыслу объяснение, настаивать формой незачем."""
    a = make_user("a")
    doc = make_doc()
    make_route([(1, "Проверка", Quorum.ALL, [a.pk], NEEDS_COMMENT)])
    process = engine.start(subject_type=SUBJECT, subject_id=doc.pk,
                           initiator_id=a.pk)

    engine.act(task_id=task_for(process, a.pk).pk, actor_id=a.pk,
               decision="reject")

    process.refresh_from_db()
    assert process.state == ProcessState.REJECTED


def test_the_comment_requirement_comes_from_the_snapshot_not_the_route():
    """Снять галочку в маршруте посреди согласования не должно избавлять от
    пояснения тех, кто ещё не решил."""
    a = make_user("a")
    doc = make_doc()
    route = make_route([(1, "Проверка", Quorum.ALL, [a.pk], NEEDS_COMMENT)])
    process = engine.start(subject_type=SUBJECT, subject_id=doc.pk,
                           initiator_id=a.pk)

    route.stages.update(requires_comment=False)

    with pytest.raises(engine.CommentRequired):
        engine.act(task_id=task_for(process, a.pk).pk, actor_id=a.pk,
                   decision="approve")


def test_deciding_without_a_comment_is_409_over_http(client):
    a = make_user("a")
    doc = make_doc()
    make_route([(1, "Проверка", Quorum.ALL, [a.pk], NEEDS_COMMENT)])
    process = engine.start(subject_type=SUBJECT, subject_id=doc.pk,
                           initiator_id=a.pk)

    refused = _decide(client, task_for(process, a.pk).pk, user_token(a))
    assert refused.status_code == 409
    assert "напишите комментарий" in refused.json()["detail"]


# ═══════════════════════════════════════════════════════════════════════
# Настройка и показ
# ═══════════════════════════════════════════════════════════════════════

def test_a_stage_requiring_a_comment_round_trips_through_the_route_api(client):
    a = make_user("a")
    route = make_route([(1, "Проверка", Quorum.ALL, [a.pk])])

    created = post_json(client, f"{BASE}/routes/{route.pk}/stages", {
        "order": 2, "name": "Обоснование", "approver_ids": [a.pk],
        "requires_comment": True,
    }, **auth(admin_token()))

    assert created.status_code == 201, created.content
    assert created.json()["requires_comment"] is True


def test_the_inbox_warns_that_a_comment_will_be_needed(client):
    a = make_user("a")
    doc = make_doc()
    make_route([(1, "Проверка", Quorum.ALL, [a.pk], NEEDS_COMMENT)])
    engine.start(subject_type=SUBJECT, subject_id=doc.pk, initiator_id=a.pk)

    inbox = client.get(f"{BASE}/tasks/mine", **auth(user_token(a))).json()
    assert inbox[0]["requires_comment"] is True


def test_the_process_card_reports_the_comment_requirement(client):
    a = make_user("a")
    doc = make_doc()
    make_route([(1, "Проверка", Quorum.ALL, [a.pk], NEEDS_COMMENT)])
    process = engine.start(subject_type=SUBJECT, subject_id=doc.pk,
                           initiator_id=a.pk)

    card = client.get(
        f"{BASE}/processes/{process.pk}", **auth(user_token(a)),
    ).json()
    assert card["stages"][0]["requires_comment"] is True
