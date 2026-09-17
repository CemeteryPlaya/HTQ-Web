"""Конвертер графов старого движка в маршруты signoff и команда переезда.

Чистая часть (``workflow_convert``) проверяется на графах в том виде, в
каком их писал конструктор; команда — на живой БД: маршрут в области
шаблона, перезапуск заявок «в пути», возврат непереносимых.
"""

from __future__ import annotations

from io import StringIO

import pytest
from django.core.management import call_command

from apps.approvals.models import (
    ApprovalAction, ApprovalActionType, RequestActivity, RequestInstance,
    RequestStatus,
)
from apps.approvals.services.workflow_convert import convert_graph
from apps.signoff.models import ApprovalProcess, ApprovalRoute, ApproverKind

from .helpers import ensure_user, make_instance, make_template


def _graph(nodes, edges):
    return {"nodes": nodes, "edges": edges}


def _ends():
    return [{"id": "ok", "type": "end_approved"}, {"id": "no", "type": "end_rejected"}]


def _approval(node_id, assignee, *, mode=None, name=None):
    node = {"id": node_id, "type": "approval", "assignee": assignee}
    if mode:
        node["mode"] = mode
    if name:
        node["name"] = name
    return node


def _chain(*approvals):
    """start → a1 → a2 → … → ok, каждый отказ → no."""
    nodes = [{"id": "start", "type": "start"}, *approvals, *_ends()]
    edges = [{"from": "start", "to": approvals[0]["id"]}]
    for current, following in zip(approvals, approvals[1:]):
        edges.append({"from": current["id"], "to": following["id"], "on": "approve"})
        edges.append({"from": current["id"], "to": "no", "on": "reject"})
    edges.append({"from": approvals[-1]["id"], "to": "ok", "on": "approve"})
    edges.append({"from": approvals[-1]["id"], "to": "no", "on": "reject"})
    return _graph(nodes, edges)


# ── чистая конвертация ───────────────────────────────────────────────────

def test_linear_chain_becomes_sequential_stages():
    graph = _chain(
        _approval("a1", {"kind": "user", "id": 11}, name="Руководитель"),
        _approval("a2", {"kind": "users", "ids": [12, 13]}, mode="all"),
        _approval("a3", {"kind": "initiator"}),
    )
    result = convert_graph(graph)
    assert result.ok, result.problems
    assert [(s.order, s.name, s.quorum, s.approver_kind, s.user_ids) for s in result.stages] == [
        (1, "Руководитель", "any", "users", [11]),
        (2, "Этап 2", "all", "users", [12, 13]),
        (3, "Этап 3", "any", "initiator", []),
    ]


def test_subject_kinds_map_to_the_objects_keys():
    graph = _chain(
        _approval("a1", {"kind": "project_admins"}),
        _approval("a2", {"kind": "field_ref", "field": "manager"}),
    )
    result = convert_graph(graph)
    assert result.ok, result.problems
    assert [(s.approver_kind, s.approver_key) for s in result.stages] == [
        ("subject", "project_admins"), ("subject", "field:manager")]


def test_condition_with_two_branches_becomes_a_group_with_fallback():
    nodes = [
        {"id": "start", "type": "start"},
        {"id": "c", "type": "condition",
         "expr": {"and": [{">": [{"var": "amount"}, 100000]},
                          {"==": [{"var": "kind"}, "Товары"]}]}},
        _approval("big", {"kind": "user", "id": 11}, name="Финдиректор"),
        _approval("small", {"kind": "user", "id": 12}, name="Руководитель"),
        _approval("last", {"kind": "initiator"}),
        *_ends(),
    ]
    edges = [
        {"from": "start", "to": "c"},
        {"from": "c", "to": "big", "when": "true"},
        {"from": "c", "to": "small", "when": "false"},
        {"from": "big", "to": "last", "on": "approve"}, {"from": "big", "to": "no", "on": "reject"},
        {"from": "small", "to": "last", "on": "approve"}, {"from": "small", "to": "no", "on": "reject"},
        {"from": "last", "to": "ok", "on": "approve"}, {"from": "last", "to": "no", "on": "reject"},
    ]
    result = convert_graph(_graph(nodes, edges))
    assert result.ok, result.problems
    big, small, last = result.stages
    assert (big.order, small.order, last.order) == (1, 1, 2)
    assert big.condition == [{"field": "amount", "op": "gt", "value": 100000},
                             {"field": "kind", "op": "eq", "value": "Товары"}]
    assert small.is_fallback and not small.condition
    assert last.approver_kind == "initiator"


def test_in_and_not_equal_map_to_set_operators():
    nodes = [
        {"id": "start", "type": "start"},
        {"id": "c", "type": "condition", "expr": {"in": [{"var": "dept"}, ["A", "B"]]}},
        _approval("yes", {"kind": "user", "id": 11}),
        _approval("no_", {"kind": "user", "id": 12}),
        *_ends(),
    ]
    edges = [
        {"from": "start", "to": "c"},
        {"from": "c", "to": "yes", "when": "true"}, {"from": "c", "to": "no_", "when": "false"},
        {"from": "yes", "to": "ok", "on": "approve"}, {"from": "yes", "to": "no", "on": "reject"},
        {"from": "no_", "to": "ok", "on": "approve"}, {"from": "no_", "to": "no", "on": "reject"},
    ]
    result = convert_graph(_graph(nodes, edges))
    assert result.ok, result.problems
    assert result.stages[0].condition == [{"field": "dept", "op": "in", "value": ["A", "B"]}]


@pytest.mark.parametrize("assignee, fragment", [
    ({"kind": "department_head"}, "не переносится"),
    ({"kind": "role", "name": "admin"}, "не переносится"),
    ({"kind": "users", "ids": []}, "не назван"),
])
def test_unsupported_assignees_are_reported(assignee, fragment):
    result = convert_graph(_chain(_approval("a1", assignee)))
    assert not result.ok and fragment in result.problems[0]


def test_branch_without_a_stage_is_reported():
    """У signoff группа без сработавшего этапа роняет запуск — нужен явный
    этап «иначе», и конвертер не выдумывает его сам."""
    nodes = [
        {"id": "start", "type": "start"},
        {"id": "c", "type": "condition", "expr": {">": [{"var": "amount"}, 10]}},
        _approval("big", {"kind": "user", "id": 11}),
        *_ends(),
    ]
    edges = [
        {"from": "start", "to": "c"},
        {"from": "c", "to": "big", "when": "true"}, {"from": "c", "to": "ok", "when": "false"},
        {"from": "big", "to": "ok", "on": "approve"}, {"from": "big", "to": "no", "on": "reject"},
    ]
    result = convert_graph(_graph(nodes, edges))
    assert not result.ok and "ветка без этапа" in result.problems[0]


def test_or_conditions_and_reject_detours_are_reported():
    nodes = [
        {"id": "start", "type": "start"},
        {"id": "c", "type": "condition", "expr": {"or": [{">": [{"var": "a"}, 1]}, {"<": [{"var": "b"}, 2]}]}},
        _approval("x", {"kind": "user", "id": 11}), _approval("y", {"kind": "user", "id": 12}),
        *_ends(),
    ]
    edges = [
        {"from": "start", "to": "c"},
        {"from": "c", "to": "x", "when": "true"}, {"from": "c", "to": "y", "when": "false"},
        {"from": "x", "to": "ok", "on": "approve"}, {"from": "x", "to": "no", "on": "reject"},
        {"from": "y", "to": "ok", "on": "approve"}, {"from": "y", "to": "no", "on": "reject"},
    ]
    assert "«or»" in convert_graph(_graph(nodes, edges)).problems[0]

    # Отказ, ведущий на другой этап, а не в end_rejected.
    detour = _chain(_approval("a1", {"kind": "user", "id": 11}),
                    _approval("a2", {"kind": "user", "id": 12}))
    detour["edges"] = [e for e in detour["edges"] if not (e["from"] == "a1" and e.get("on") == "reject")]
    detour["edges"].append({"from": "a1", "to": "a2", "on": "reject"})
    assert "отказ на этапе" in convert_graph(detour).problems[0]


def test_graph_without_approvals_is_reported():
    graph = _graph([{"id": "s", "type": "start"}, {"id": "ok", "type": "end_approved"}],
                   [{"from": "s", "to": "ok"}])
    assert "ни одного этапа" in convert_graph(graph).problems[0]


# ── команда переезда ─────────────────────────────────────────────────────

def _legacy_workflow(*user_ids: int) -> dict:
    return _chain(_approval("a1", {"kind": "users", "ids": list(user_ids)},
                            mode="all", name="Проверка"))


@pytest.mark.django_db
def test_command_creates_routes_and_restarts_pending_requests():
    ensure_user(11), ensure_user(12)
    template = make_template(slug="legacy", route=False, workflow=_legacy_workflow(11, 12))
    # Заявка «в пути» на старом движке: один уже одобрил, второй ждёт.
    pending = make_instance(template, status=RequestStatus.PENDING)
    pending.current_node_id = "a1"
    pending.save(update_fields=["current_node_id"])
    ApprovalAction.objects.create(request=pending, node_id="a1", approver_id=11,
                                  action=ApprovalActionType.APPROVE, acted_at="2026-01-01T00:00:00Z")
    ApprovalAction.objects.create(request=pending, node_id="a1", approver_id=12)
    finished = make_instance(template, status=RequestStatus.APPROVED)

    out = StringIO()
    call_command("migrate_workflows_to_signoff", "--dry-run", stdout=out)
    assert "маршрут → 1. Проверка [users [11, 12]]" in out.getvalue()
    assert not ApprovalRoute.objects.exists()  # dry-run ничего не пишет

    out = StringIO()
    call_command("migrate_workflows_to_signoff", stdout=out)
    route = ApprovalRoute.objects.get(scope=f"template:{template.id}")
    stage = route.stages.get()
    assert stage.approver_kind == ApproverKind.USERS and stage.user_ids == [11, 12]
    assert stage.quorum == "all"

    pending.refresh_from_db()
    assert pending.status == RequestStatus.PENDING
    assert pending.approval_state == "pending"
    assert pending.current_node_id is None
    process = ApprovalProcess.objects.get(subject_id=pending.pk)
    assert sorted(t.user_id for t in process.stages.get().tasks.all()) == [11, 12]
    note = RequestActivity.objects.get(request=pending, event_type="migrated_to_signoff")
    assert note.payload["approved_by"] == [11] and note.payload["action"] == "restarted"
    # Старые слоты закрыты, а завершённая заявка не тронута.
    assert not ApprovalAction.objects.filter(request=pending, acted_at__isnull=True).exists()
    finished.refresh_from_db()
    assert finished.status == RequestStatus.APPROVED
    assert not ApprovalProcess.objects.filter(subject_id=finished.pk).exists()

    # Повторный прогон — идемпотентен.
    out = StringIO()
    call_command("migrate_workflows_to_signoff", stdout=out)
    assert "маршрут уже есть" in out.getvalue()
    assert ApprovalProcess.objects.filter(subject_id=pending.pk).count() == 1


@pytest.mark.django_db
def test_command_returns_requests_of_unconvertible_templates():
    template = make_template(
        slug="legacy-bad", route=False,
        workflow=_chain(_approval("a1", {"kind": "department_head"})))
    pending = make_instance(template, status=RequestStatus.PENDING)

    out = StringIO()
    call_command("migrate_workflows_to_signoff", stdout=out)
    assert "НЕ переносится" in out.getvalue()
    assert not ApprovalRoute.objects.exists()
    pending.refresh_from_db()
    assert pending.status == RequestStatus.RETURNED
    assert pending.approval_state == "rework"
    note = RequestActivity.objects.get(request=pending, event_type="migrated_to_signoff")
    assert note.payload["action"] == "returned"


@pytest.mark.django_db
def test_command_returns_request_the_new_route_refuses():
    """Маршрут перенесён, но согласующий уже уволен — движок такой запуск не
    примет, и заявка возвращается инициатору, а не виснет."""
    ensure_user(11)
    template = make_template(slug="legacy-gone", route=False, workflow=_legacy_workflow(11))
    pending = make_instance(template, status=RequestStatus.PENDING)
    gone = ensure_user(11)
    gone.status = "suspended"
    gone.save(update_fields=["status"])

    out = StringIO()
    call_command("migrate_workflows_to_signoff", stdout=out)
    assert "не принят движком" in out.getvalue()  # USERS-этап с неактивным — 409 на настройке
    pending.refresh_from_db()
    assert pending.status == RequestStatus.RETURNED
