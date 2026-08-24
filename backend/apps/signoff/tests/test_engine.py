"""Движок согласования: последовательность, параллельность, кворум, отказ.

Это главные тесты аппки. Всё остальное (HTTP, админка, фронтенд) — обвязка
вокруг переходов, проверяемых здесь.
"""

from __future__ import annotations

import pytest

from apps.signoff.models import (
    ApprovalEvent,
    ApprovalProcess,
    ApprovalState,
    ApprovalTask,
    ProcessState,
    Quorum,
    StageState,
    TaskState,
)
from apps.signoff.services import engine
from apps.hr.models import Employee, EmployeeStatus
from apps.signoff.tests.helpers import (
    active_user_ids,
    make_doc,
    make_route,
    make_user,
    simple_route,
    stage_states,
    task_for,
)
from apps.signoff.tests.testapp import hooks
from apps.signoff.tests.testapp.models import ProbeDoc

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _reset_calls():
    hooks.reset()
    yield
    hooks.reset()


# ═══════════════════════════════════════════════════════════════════════
# Запуск
# ═══════════════════════════════════════════════════════════════════════

def test_start_creates_stage_snapshot_and_activates_only_the_first_group():
    a, b, c = make_user("a"), make_user("b"), make_user("c")
    doc = make_doc()
    make_route([
        (1, "Первый", Quorum.ALL, [a.pk]),
        (2, "Второй", Quorum.ALL, [b.pk]),
        (3, "Третий", Quorum.ALL, [c.pk]),
    ])

    process = engine.start(subject_type=ProbeDoc.SIGNOFF_SUBJECT_TYPE,
                           subject_id=doc.pk, initiator_id=99)

    assert process.state == ProcessState.PENDING
    assert process.current_order == 1
    assert stage_states(process) == [StageState.ACTIVE, StageState.WAITING,
                                     StageState.WAITING]
    # Запрос ушёл ТОЛЬКО первому — остальные не должны видеть его в своём
    # списке, пока очередь не дошла.
    assert active_user_ids(process) == {a.pk}
    assert ApprovalTask.objects.filter(stage__process=process).count() == 3

    doc.refresh_from_db()
    assert doc.approval_state == ApprovalState.PENDING
    assert ("started", doc.pk) in hooks.CALLS


def test_stage_snapshot_survives_a_later_edit_of_the_route():
    """Правка маршрута не меняет правила уже идущего согласования."""
    a, b = make_user("a"), make_user("b")
    doc = make_doc()
    route = make_route([(1, "Исходный этап", Quorum.ALL, [a.pk])])

    process = engine.start(subject_type=ProbeDoc.SIGNOFF_SUBJECT_TYPE,
                           subject_id=doc.pk)

    stage = route.stages.first()
    stage.name = "Переименованный этап"
    stage.save()
    stage.roles.all().delete()
    stage.roles.create(position_id=b.pk)

    process.refresh_from_db()
    snapshot = process.stages.first()
    assert snapshot.name == "Исходный этап"
    assert active_user_ids(process) == {a.pk}


def test_route_resolves_the_current_employee_in_a_position():
    former, replacement = make_user("former"), make_user("replacement")
    doc = make_doc()
    make_route([(1, "Финансовый контроль", Quorum.ALL, [former.pk])])

    # The route still refers to former's POSITION.  HR changes the holder
    # before this process starts, so the new employee receives the task.
    Employee.objects.filter(user_id=former.pk).update(status=EmployeeStatus.TERMINATED)
    Employee.objects.filter(user_id=replacement.pk).update(position_id=former.pk)

    process = engine.start(subject_type=ProbeDoc.SIGNOFF_SUBJECT_TYPE,
                           subject_id=doc.pk)
    assert active_user_ids(process) == {replacement.pk}
    assert process.stages.get().role_ids == [former.pk]


def test_start_without_a_route_is_refused():
    doc = make_doc()
    with pytest.raises(engine.RouteNotConfigured):
        engine.start(subject_type=ProbeDoc.SIGNOFF_SUBJECT_TYPE, subject_id=doc.pk)


def test_start_refuses_a_stage_with_no_approvers():
    doc = make_doc()
    make_route([(1, "Пустой этап", Quorum.ALL, [])])
    with pytest.raises(engine.RouteUnusable, match="Пустой этап"):
        engine.start(subject_type=ProbeDoc.SIGNOFF_SUBJECT_TYPE, subject_id=doc.pk)


def test_start_refuses_a_stage_whose_approvers_all_left():
    """Согласующие заданы поимённо — маршрут переживает увольнения плохо.

    Лучше отказать на запуске, чем создать процесс, который физически
    некому двигать.
    """
    gone = make_user("gone", active=False)
    doc = make_doc()
    make_route([(1, "Осиротевший этап", Quorum.ALL, [gone.pk])])

    with pytest.raises(engine.RouteUnusable, match="активного"):
        engine.start(subject_type=ProbeDoc.SIGNOFF_SUBJECT_TYPE, subject_id=doc.pk)

    assert not ApprovalProcess.objects.exists()


def test_start_twice_on_the_same_object_is_refused():
    a = make_user("a")
    doc = make_doc()
    simple_route(a.pk)

    engine.start(subject_type=ProbeDoc.SIGNOFF_SUBJECT_TYPE, subject_id=doc.pk)
    with pytest.raises(engine.AlreadyInApproval):
        engine.start(subject_type=ProbeDoc.SIGNOFF_SUBJECT_TYPE, subject_id=doc.pk)


def test_unregistered_subject_type_is_refused():
    with pytest.raises(engine.registry.UnknownSubject):
        engine.start(subject_type="nosuch.model", subject_id=1)


# ═══════════════════════════════════════════════════════════════════════
# Последовательные этапы
# ═══════════════════════════════════════════════════════════════════════

def test_sequential_stages_advance_one_group_at_a_time():
    a, b, c = make_user("a"), make_user("b"), make_user("c")
    doc = make_doc()
    make_route([
        (1, "Первый", Quorum.ALL, [a.pk]),
        (2, "Второй", Quorum.ALL, [b.pk]),
        (3, "Третий", Quorum.ALL, [c.pk]),
    ])
    process = engine.start(subject_type=ProbeDoc.SIGNOFF_SUBJECT_TYPE,
                           subject_id=doc.pk)

    engine.act(task_id=task_for(process, a.pk).pk, actor_id=a.pk,
               decision=engine.APPROVE)
    process.refresh_from_db()
    assert process.current_order == 2
    assert active_user_ids(process) == {b.pk}

    engine.act(task_id=task_for(process, b.pk).pk, actor_id=b.pk,
               decision=engine.APPROVE)
    process.refresh_from_db()
    assert process.current_order == 3
    assert active_user_ids(process) == {c.pk}

    engine.act(task_id=task_for(process, c.pk).pk, actor_id=c.pk,
               decision=engine.APPROVE)
    process.refresh_from_db()
    assert process.state == ProcessState.APPROVED
    assert process.current_order is None
    assert process.finished_at is not None

    doc.refresh_from_db()
    assert doc.approval_state == ApprovalState.APPROVED
    # Доменное последствие — дело предметной аппки, а не signoff.
    assert doc.published is True
    assert hooks.CALLS.count(("approved", doc.pk)) == 1


# ═══════════════════════════════════════════════════════════════════════
# Параллельные этапы
# ═══════════════════════════════════════════════════════════════════════

def test_stages_sharing_an_order_run_in_parallel():
    a, b, c = make_user("a"), make_user("b"), make_user("c")
    doc = make_doc()
    make_route([
        (1, "Финансовый контроль", Quorum.ALL, [a.pk]),
        (1, "Юридическая проверка", Quorum.ALL, [b.pk]),
        (2, "Утверждение", Quorum.ALL, [c.pk]),
    ])
    process = engine.start(subject_type=ProbeDoc.SIGNOFF_SUBJECT_TYPE,
                           subject_id=doc.pk)

    # Оба этапа первой очереди активны сразу.
    assert active_user_ids(process) == {a.pk, b.pk}

    engine.act(task_id=task_for(process, a.pk).pk, actor_id=a.pk,
               decision=engine.APPROVE)
    process.refresh_from_db()
    # Один из двух параллельных закрыт — очередь НЕ двигается.
    assert process.current_order == 1
    assert active_user_ids(process) == {b.pk}

    engine.act(task_id=task_for(process, b.pk).pk, actor_id=b.pk,
               decision=engine.APPROVE)
    process.refresh_from_db()
    assert process.current_order == 2
    assert active_user_ids(process) == {c.pk}


def test_parallel_stages_can_be_approved_in_any_order():
    a, b = make_user("a"), make_user("b")
    doc = make_doc()
    make_route([
        (1, "Левый", Quorum.ALL, [a.pk]),
        (1, "Правый", Quorum.ALL, [b.pk]),
    ])
    process = engine.start(subject_type=ProbeDoc.SIGNOFF_SUBJECT_TYPE,
                           subject_id=doc.pk)

    engine.act(task_id=task_for(process, b.pk).pk, actor_id=b.pk,
               decision=engine.APPROVE)
    engine.act(task_id=task_for(process, a.pk).pk, actor_id=a.pk,
               decision=engine.APPROVE)

    process.refresh_from_db()
    assert process.state == ProcessState.APPROVED
    # Колбэк ровно один, хотя закрывающих этапов было два.
    assert hooks.CALLS.count(("approved", doc.pk)) == 1


# ═══════════════════════════════════════════════════════════════════════
# Кворум внутри этапа
# ═══════════════════════════════════════════════════════════════════════

def test_quorum_all_needs_every_approver():
    a, b = make_user("a"), make_user("b")
    doc = make_doc()
    simple_route(a.pk, b.pk, quorum=Quorum.ALL)
    process = engine.start(subject_type=ProbeDoc.SIGNOFF_SUBJECT_TYPE,
                           subject_id=doc.pk)

    engine.act(task_id=task_for(process, a.pk).pk, actor_id=a.pk,
               decision=engine.APPROVE)
    process.refresh_from_db()
    assert process.state == ProcessState.PENDING
    assert active_user_ids(process) == {b.pk}

    engine.act(task_id=task_for(process, b.pk).pk, actor_id=b.pk,
               decision=engine.APPROVE)
    process.refresh_from_db()
    assert process.state == ProcessState.APPROVED


def test_quorum_any_closes_the_stage_on_the_first_approval():
    a, b = make_user("a"), make_user("b")
    doc = make_doc()
    simple_route(a.pk, b.pk, quorum=Quorum.ANY)
    process = engine.start(subject_type=ProbeDoc.SIGNOFF_SUBJECT_TYPE,
                           subject_id=doc.pk)

    engine.act(task_id=task_for(process, a.pk).pk, actor_id=a.pk,
               decision=engine.APPROVE)

    process.refresh_from_db()
    assert process.state == ProcessState.APPROVED
    # Запрос второго погашен, а не висит у него в списке навсегда.
    leftover = ApprovalTask.objects.get(stage__process=process, user_id=b.pk)
    assert leftover.state == TaskState.SKIPPED


def test_quorum_any_needs_one_approval_from_every_selected_position():
    controller, deputy, manager = (make_user("controller"),
                                   make_user("deputy"),
                                   make_user("manager"))
    # Two people hold the controller position; they represent one required
    # role, whereas the manager position is a separate required role.
    Employee.objects.filter(user_id=deputy.pk).update(position_id=controller.pk)
    doc = make_doc()
    simple_route(controller.pk, manager.pk, quorum=Quorum.ANY)
    process = engine.start(subject_type=ProbeDoc.SIGNOFF_SUBJECT_TYPE,
                           subject_id=doc.pk)

    tasks = {task.user_id: task for task in process.stages.get().tasks.all()}
    assert tasks[controller.pk].position_id == controller.pk
    assert tasks[deputy.pk].position_id == controller.pk
    assert tasks[manager.pk].position_id == manager.pk

    engine.act(task_id=tasks[controller.pk].pk, actor_id=controller.pk,
               decision=engine.APPROVE)
    process.refresh_from_db()
    assert process.state == ProcessState.PENDING
    assert active_user_ids(process) == {manager.pk}
    tasks[deputy.pk].refresh_from_db()
    assert tasks[deputy.pk].state == TaskState.SKIPPED
    with pytest.raises(engine.ProcessClosed):
        engine.act(task_id=tasks[deputy.pk].pk, actor_id=deputy.pk,
                   decision=engine.REJECT)

    engine.act(task_id=tasks[manager.pk].pk, actor_id=manager.pk,
               decision=engine.APPROVE)
    process.refresh_from_db()
    assert process.state == ProcessState.APPROVED


def test_quorum_all_needs_every_holder_of_every_selected_position():
    controller, deputy, manager = (make_user("controller"),
                                   make_user("deputy"),
                                   make_user("manager"))
    Employee.objects.filter(user_id=deputy.pk).update(position_id=controller.pk)
    doc = make_doc()
    simple_route(controller.pk, manager.pk, quorum=Quorum.ALL)
    process = engine.start(subject_type=ProbeDoc.SIGNOFF_SUBJECT_TYPE,
                           subject_id=doc.pk)
    tasks = {task.user_id: task for task in process.stages.get().tasks.all()}

    engine.act(task_id=tasks[controller.pk].pk, actor_id=controller.pk,
               decision=engine.APPROVE)
    engine.act(task_id=tasks[manager.pk].pk, actor_id=manager.pk,
               decision=engine.APPROVE)
    process.refresh_from_db()
    assert process.state == ProcessState.PENDING
    assert active_user_ids(process) == {deputy.pk}

    engine.act(task_id=tasks[deputy.pk].pk, actor_id=deputy.pk,
               decision=engine.APPROVE)
    process.refresh_from_db()
    assert process.state == ProcessState.APPROVED


# ═══════════════════════════════════════════════════════════════════════
# Отказ решает судьбу всего процесса
# ═══════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("reject_at", [1, 2, 3])
def test_a_rejection_at_any_stage_rejects_the_whole_process(reject_at):
    users = [make_user("a"), make_user("b"), make_user("c")]
    doc = make_doc()
    make_route([
        (order, f"Этап {order}", Quorum.ALL, [user.pk])
        for order, user in enumerate(users, start=1)
    ])
    process = engine.start(subject_type=ProbeDoc.SIGNOFF_SUBJECT_TYPE,
                           subject_id=doc.pk)

    # Доводим процесс до нужного этапа согласованиями.
    for user in users[:reject_at - 1]:
        engine.act(task_id=task_for(process, user.pk).pk, actor_id=user.pk,
                   decision=engine.APPROVE)

    rejecter = users[reject_at - 1]
    engine.act(task_id=task_for(process, rejecter.pk).pk, actor_id=rejecter.pk,
               decision=engine.REJECT, comment="не согласен")

    process.refresh_from_db()
    assert process.state == ProcessState.REJECTED
    assert process.current_order is None

    states = stage_states(process)
    # Пройденные — согласованы, отказавший — отклонён, остальные —
    # «не потребовался»: в карточке должно быть видно, КТО отказал.
    assert states[:reject_at - 1] == [StageState.APPROVED] * (reject_at - 1)
    assert states[reject_at - 1] == StageState.REJECTED
    assert states[reject_at:] == [StageState.SKIPPED] * (len(states) - reject_at)

    assert not ApprovalTask.objects.filter(
        stage__process=process, state=TaskState.PENDING).exists()

    doc.refresh_from_db()
    assert doc.approval_state == ApprovalState.REJECTED
    assert doc.published is False
    assert hooks.CALLS.count(("rejected", doc.pk)) == 1
    assert ("approved", doc.pk) not in hooks.CALLS


def test_rejection_on_one_parallel_stage_kills_its_sibling():
    a, b, c = make_user("a"), make_user("b"), make_user("c")
    doc = make_doc()
    make_route([
        (1, "Левый", Quorum.ALL, [a.pk]),
        (1, "Правый", Quorum.ALL, [b.pk]),
        (2, "Утверждение", Quorum.ALL, [c.pk]),
    ])
    process = engine.start(subject_type=ProbeDoc.SIGNOFF_SUBJECT_TYPE,
                           subject_id=doc.pk)

    engine.act(task_id=task_for(process, a.pk).pk, actor_id=a.pk,
               decision=engine.REJECT)

    process.refresh_from_db()
    assert process.state == ProcessState.REJECTED
    # Параллельный сосед не должен остаться висеть в списке у b.
    assert active_user_ids(process) == set()
    assert stage_states(process) == [StageState.REJECTED, StageState.SKIPPED,
                                     StageState.SKIPPED]


def test_rejection_wins_over_an_approval_in_the_same_stage():
    a, b = make_user("a"), make_user("b")
    doc = make_doc()
    simple_route(a.pk, b.pk, quorum=Quorum.ALL)
    process = engine.start(subject_type=ProbeDoc.SIGNOFF_SUBJECT_TYPE,
                           subject_id=doc.pk)

    engine.act(task_id=task_for(process, a.pk).pk, actor_id=a.pk,
               decision=engine.APPROVE)
    engine.act(task_id=task_for(process, b.pk).pk, actor_id=b.pk,
               decision=engine.REJECT)

    process.refresh_from_db()
    assert process.state == ProcessState.REJECTED


# ═══════════════════════════════════════════════════════════════════════
# Права и повторные решения
# ═══════════════════════════════════════════════════════════════════════

def test_someone_elses_task_cannot_be_decided():
    a, b = make_user("a"), make_user("b")
    doc = make_doc()
    simple_route(a.pk)
    process = engine.start(subject_type=ProbeDoc.SIGNOFF_SUBJECT_TYPE,
                           subject_id=doc.pk)

    with pytest.raises(engine.NotAnApprover):
        engine.act(task_id=task_for(process, a.pk).pk, actor_id=b.pk,
                   decision=engine.APPROVE)


def test_a_task_cannot_be_decided_twice():
    a, b = make_user("a"), make_user("b")
    doc = make_doc()
    simple_route(a.pk, b.pk, quorum=Quorum.ALL)
    process = engine.start(subject_type=ProbeDoc.SIGNOFF_SUBJECT_TYPE,
                           subject_id=doc.pk)

    task = task_for(process, a.pk)
    engine.act(task_id=task.pk, actor_id=a.pk, decision=engine.APPROVE)
    with pytest.raises(engine.ProcessClosed):
        engine.act(task_id=task.pk, actor_id=a.pk, decision=engine.REJECT)


def test_no_decisions_are_accepted_after_the_process_closed():
    a, b = make_user("a"), make_user("b")
    doc = make_doc()
    make_route([
        (1, "Первый", Quorum.ALL, [a.pk]),
        (2, "Второй", Quorum.ALL, [b.pk]),
    ])
    process = engine.start(subject_type=ProbeDoc.SIGNOFF_SUBJECT_TYPE,
                           subject_id=doc.pk)

    second = ApprovalTask.objects.get(stage__process=process, user_id=b.pk)
    engine.act(task_id=task_for(process, a.pk).pk, actor_id=a.pk,
               decision=engine.REJECT)

    with pytest.raises(engine.ProcessClosed):
        engine.act(task_id=second.pk, actor_id=b.pk, decision=engine.APPROVE)


def test_unknown_decision_is_refused():
    a = make_user("a")
    doc = make_doc()
    simple_route(a.pk)
    process = engine.start(subject_type=ProbeDoc.SIGNOFF_SUBJECT_TYPE,
                           subject_id=doc.pk)

    with pytest.raises(engine.SignoffError):
        engine.act(task_id=task_for(process, a.pk).pk, actor_id=a.pk,
                   decision="maybe")


# ═══════════════════════════════════════════════════════════════════════
# Возврат на доработку
# ═══════════════════════════════════════════════════════════════════════
#
# Отличается от отказа ровно одним, зато главным: судьбой предметного
# объекта. Круг оба закрывают одинаково, но отклонённый объект остаётся
# запертым, а возвращённый — правится (``models.ApprovalState``).

def test_rework_closes_the_process_and_unlocks_the_object():
    a, b = make_user("a"), make_user("b")
    doc = make_doc()
    make_route([
        (1, "Первый", Quorum.ALL, [a.pk]),
        (2, "Второй", Quorum.ALL, [b.pk]),
    ])
    process = engine.start(subject_type=ProbeDoc.SIGNOFF_SUBJECT_TYPE,
                           subject_id=doc.pk)

    engine.act(task_id=task_for(process, a.pk).pk, actor_id=a.pk,
               decision=engine.REWORK, comment="исправьте сумму")

    process.refresh_from_db()
    assert process.state == ProcessState.REWORK
    assert process.current_order is None
    # Как и при отказе: вернувший этап помечен, остальные «не потребовались».
    assert stage_states(process) == [StageState.REWORK, StageState.SKIPPED]
    assert active_user_ids(process) == set()

    task = ApprovalTask.objects.get(stage__process=process, user_id=a.pk)
    assert task.state == TaskState.REWORK
    assert task.comment == "исправьте сумму"

    doc.refresh_from_db()
    assert doc.approval_state == ApprovalState.REWORK
    assert doc.is_editable is True
    assert hooks.CALLS.count(("rework", doc.pk)) == 1
    assert ("rejected", doc.pk) not in hooks.CALLS


def test_a_reworked_object_goes_through_a_new_process():
    """Доработанный объект отправляют ЗАНОВО — новым кругом, а не
    продолжением старого: маршрут и факты на новом запуске уже другие."""
    a = make_user("a")
    doc = make_doc()
    simple_route(a.pk)
    first = engine.start(subject_type=ProbeDoc.SIGNOFF_SUBJECT_TYPE,
                         subject_id=doc.pk)
    engine.act(task_id=task_for(first, a.pk).pk, actor_id=a.pk,
               decision=engine.REWORK)

    second = engine.start(subject_type=ProbeDoc.SIGNOFF_SUBJECT_TYPE,
                          subject_id=doc.pk)
    assert second.pk != first.pk
    assert second.state == ProcessState.PENDING


@pytest.mark.parametrize("decision, state", [
    (engine.APPROVE, ApprovalState.APPROVED),
    (engine.REJECT, ApprovalState.REJECTED),
])
def test_a_decided_object_cannot_be_submitted_again(decision, state):
    """Ни согласованный, ни отклонённый: оба заперты для правки, и новый круг
    прошёл бы по тому же самому содержимому."""
    a = make_user("a")
    doc = make_doc()
    simple_route(a.pk)
    process = engine.start(subject_type=ProbeDoc.SIGNOFF_SUBJECT_TYPE,
                           subject_id=doc.pk)
    engine.act(task_id=task_for(process, a.pk).pk, actor_id=a.pk,
               decision=decision)

    doc.refresh_from_db()
    assert doc.approval_state == state

    with pytest.raises(engine.SubjectLocked):
        engine.start(subject_type=ProbeDoc.SIGNOFF_SUBJECT_TYPE,
                     subject_id=doc.pk)


@pytest.mark.parametrize("decision, from_state", [
    (engine.APPROVE, ProcessState.APPROVED),
    (engine.REJECT, ProcessState.REJECTED),
])
def test_reopen_unlocks_an_already_decided_object(decision, from_state):
    """Второй вход в доработку: круг закрыт, а объект надо править. Без него
    «согласовано» было бы состоянием, из которого нет выхода."""
    a = make_user("a")
    doc = make_doc()
    simple_route(a.pk)
    process = engine.start(subject_type=ProbeDoc.SIGNOFF_SUBJECT_TYPE,
                           subject_id=doc.pk, initiator_id=42)
    engine.act(task_id=task_for(process, a.pk).pk, actor_id=a.pk,
               decision=decision)
    finished_at = ApprovalProcess.objects.get(pk=process.pk).finished_at

    engine.reopen(process_id=process.pk, actor_id=a.pk, comment="не та сумма")

    process.refresh_from_db()
    assert process.state == ProcessState.REWORK
    # Круг закончился тогда, когда его закончило решение: момент возврата
    # хранит событие журнала, а не это поле.
    assert process.finished_at == finished_at

    doc.refresh_from_db()
    assert doc.approval_state == ApprovalState.REWORK
    assert doc.is_editable is True
    # Доменное последствие отыграно назад — тем же колбэком, что и у
    # решения «на доработку».
    assert doc.published is False
    assert hooks.CALLS.count(("rework", doc.pk)) == 1

    event = ApprovalEvent.objects.filter(process=process).order_by("id").last()
    assert event.kind == "reopened"
    assert event.payload == {"from": from_state, "comment": "не та сумма"}


def test_reopening_a_running_process_is_refused():
    a = make_user("a")
    doc = make_doc()
    simple_route(a.pk)
    process = engine.start(subject_type=ProbeDoc.SIGNOFF_SUBJECT_TYPE,
                           subject_id=doc.pk)

    with pytest.raises(engine.ProcessStillRunning):
        engine.reopen(process_id=process.pk, actor_id=a.pk)


def test_reopening_twice_is_refused():
    """Объект уже открыт — второй возврат нечего отпирать."""
    a = make_user("a")
    doc = make_doc()
    simple_route(a.pk)
    process = engine.start(subject_type=ProbeDoc.SIGNOFF_SUBJECT_TYPE,
                           subject_id=doc.pk)
    engine.act(task_id=task_for(process, a.pk).pk, actor_id=a.pk,
               decision=engine.APPROVE)
    engine.reopen(process_id=process.pk, actor_id=a.pk)

    with pytest.raises(engine.ProcessClosed):
        engine.reopen(process_id=process.pk, actor_id=a.pk)


# ═══════════════════════════════════════════════════════════════════════
# Отзыв
# ═══════════════════════════════════════════════════════════════════════

def test_cancel_returns_the_object_to_draft_and_frees_it_for_resubmission():
    a = make_user("a")
    doc = make_doc()
    simple_route(a.pk)
    process = engine.start(subject_type=ProbeDoc.SIGNOFF_SUBJECT_TYPE,
                           subject_id=doc.pk, initiator_id=42)

    engine.cancel(process_id=process.pk, actor_id=42)

    process.refresh_from_db()
    assert process.state == ProcessState.CANCELLED
    assert not ApprovalTask.objects.filter(
        stage__process=process, state=TaskState.PENDING).exists()

    doc.refresh_from_db()
    # Отзыв — не отказ: объект снова черновик и отправляется заново.
    assert doc.approval_state == ApprovalState.DRAFT
    assert hooks.CALLS.count(("cancelled", doc.pk)) == 1

    again = engine.start(subject_type=ProbeDoc.SIGNOFF_SUBJECT_TYPE,
                         subject_id=doc.pk)
    assert again.state == ProcessState.PENDING


def test_cancelling_a_finished_process_is_refused():
    a = make_user("a")
    doc = make_doc()
    simple_route(a.pk)
    process = engine.start(subject_type=ProbeDoc.SIGNOFF_SUBJECT_TYPE,
                           subject_id=doc.pk)
    engine.act(task_id=task_for(process, a.pk).pk, actor_id=a.pk,
               decision=engine.APPROVE)

    with pytest.raises(engine.ProcessClosed):
        engine.cancel(process_id=process.pk)


# ═══════════════════════════════════════════════════════════════════════
# Замок: что правится, а что нет
# ═══════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("state, editable", [
    (ApprovalState.DRAFT, True),
    (ApprovalState.REWORK, True),
    (ApprovalState.PENDING, False),
    (ApprovalState.APPROVED, False),
    (ApprovalState.REJECTED, False),
])
def test_assert_editable_covers_every_state(state, editable):
    """Таблица целиком, а не пара случаев: список состояний растёт, и
    забытое в нём — это молча открытый документ либо запертый навсегда."""
    doc = make_doc()
    ProbeDoc.objects.filter(pk=doc.pk).update(approval_state=state)
    doc.refresh_from_db()

    assert doc.is_editable is editable
    if editable:
        doc.assert_editable()  # не поднимает
    else:
        with pytest.raises(engine.SubjectLocked):
            doc.assert_editable()


def test_every_locked_state_explains_itself():
    """У каждого запертого состояния — свой текст: следующее действие
    человека в них РАЗНОЕ (дождаться решения / вернуть на доработку), и
    общее «объект заперт» не подсказало бы ни одного из них."""
    locked = set(ApprovalState.values) - ApprovalState.editable()
    assert locked == set(ProbeDoc._LOCK_REASONS)


def test_a_disabled_signoff_unlocks_everything():
    """Выключенный модуль согласования перестаёт ТРЕБОВАТЬ согласования, а
    не запирает подключившие его аппки: отпереть объект иначе было бы нечем
    — и возврат на доработку, и отзыв стоят за ``require_service``."""
    from apps.core.models import ServiceStatus

    doc = make_doc()
    ProbeDoc.objects.filter(pk=doc.pk).update(
        approval_state=ApprovalState.APPROVED)
    doc.refresh_from_db()
    ServiceStatus.objects.update_or_create(
        app_label="signoff", defaults={"enabled": False, "message": "off"})

    doc.assert_editable()  # не поднимает


# ═══════════════════════════════════════════════════════════════════════
# Журнал
# ═══════════════════════════════════════════════════════════════════════

def test_the_event_log_records_the_whole_route():
    a, b = make_user("a"), make_user("b")
    doc = make_doc()
    make_route([
        (1, "Первый", Quorum.ALL, [a.pk]),
        (2, "Второй", Quorum.ALL, [b.pk]),
    ])
    process = engine.start(subject_type=ProbeDoc.SIGNOFF_SUBJECT_TYPE,
                           subject_id=doc.pk, initiator_id=1)
    engine.act(task_id=task_for(process, a.pk).pk, actor_id=a.pk,
               decision=engine.APPROVE)
    engine.act(task_id=task_for(process, b.pk).pk, actor_id=b.pk,
               decision=engine.REJECT, comment="нет")

    kinds = list(ApprovalEvent.objects.filter(process=process)
                 .order_by("id").values_list("kind", flat=True))
    assert kinds == ["started", "task_approved", "stage_activated",
                     "task_rejected", "rejected"]

    last = ApprovalEvent.objects.filter(process=process).order_by("id").last()
    assert last.payload["comment"] == "нет"
