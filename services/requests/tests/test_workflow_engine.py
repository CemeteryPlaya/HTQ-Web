import pytest

from app.services.workflow_engine import (
    WorkflowError,
    build_runtime,
    first_actionable,
    next_actionable,
    resolve_outcome,
)

_WF = {
    "nodes": [
        {"id": "s", "type": "start"},
        {"id": "pm", "type": "approval", "assignee": {"kind": "project_admins"}, "mode": "any"},
        {"id": "note", "type": "notify"},
        {"id": "fin", "type": "approval", "assignee": {"kind": "user", "id": 9}, "mode": "all"},
        {"id": "ok", "type": "end_approved"},
        {"id": "no", "type": "end_rejected"},
    ],
    "edges": [
        {"from": "s", "to": "pm"},
        {"from": "pm", "to": "note", "on": "approve"},
        {"from": "pm", "to": "no", "on": "reject"},
        {"from": "note", "to": "fin"},
        {"from": "fin", "to": "ok", "on": "approve"},
        {"from": "fin", "to": "no", "on": "reject"},
    ],
}


def test_first_actionable_is_pm():
    rt = build_runtime(_WF)
    kind, node = first_actionable(rt)
    assert kind == "approval" and node.id == "pm"


def test_next_after_pm_approve_walks_notify_to_fin():
    rt = build_runtime(_WF)
    kind, node = next_actionable(rt, "pm", "approve")
    assert kind == "approval" and node.id == "fin"


def test_next_after_pm_reject_is_end():
    rt = build_runtime(_WF)
    kind, node = next_actionable(rt, "pm", "reject")
    assert kind == "end" and node.id == "no"


def test_next_after_fin_approve_is_end_ok():
    rt = build_runtime(_WF)
    kind, node = next_actionable(rt, "fin", "approve")
    assert kind == "end" and node.id == "ok"


def test_resolve_any_first_approve():
    assert resolve_outcome("any", [("approve", 1)]) == "approve"


def test_resolve_any_reject_wins_immediately():
    assert resolve_outcome("any", [("reject", 1)]) == "reject"


def test_resolve_all_needs_everyone():
    assert resolve_outcome("all", [("approve", 1)], total=2) is None
    assert resolve_outcome("all", [("approve", 1), ("approve", 2)], total=2) == "approve"


def test_resolve_all_any_reject_is_reject():
    assert resolve_outcome("all", [("approve", 1), ("reject", 2)], total=2) == "reject"


def _wf_with_condition():
    return {"nodes": [
        {"id": "s", "type": "start"},
        {"id": "c", "type": "condition", "expr": {">": [{"var": "amount"}, 100]}},
        {"id": "small", "type": "end_approved"},
        {"id": "big", "type": "approval", "assignee": {"kind": "user", "id": 9}, "mode": "any"},
        {"id": "ok", "type": "end_approved"},
        {"id": "no", "type": "end_rejected"}],
        "edges": [
            {"from": "s", "to": "c"},
            {"from": "c", "to": "small", "when": "false"},
            {"from": "c", "to": "big", "when": "true"},
            {"from": "big", "to": "ok", "on": "approve"},
            {"from": "big", "to": "no", "on": "reject"}]}


def test_condition_false_branch_ends_approved():
    rt = build_runtime(_wf_with_condition())
    kind, node = first_actionable(rt, form_values={"amount": 50})
    assert kind == "end" and node.id == "small"


def test_condition_true_branch_goes_to_approval():
    rt = build_runtime(_wf_with_condition())
    kind, node = first_actionable(rt, form_values={"amount": 500})
    assert kind == "approval" and node.id == "big"


def test_condition_without_expr_raises():
    wf = {"nodes": [{"id": "s", "type": "start"},
                    {"id": "c", "type": "condition"},
                    {"id": "ok", "type": "end_approved"},
                    {"id": "no", "type": "end_rejected"}],
          "edges": [{"from": "s", "to": "c"},
                    {"from": "c", "to": "ok", "when": "true"},
                    {"from": "c", "to": "no", "when": "false"}]}
    rt = build_runtime(wf)
    with pytest.raises(WorkflowError):
        first_actionable(rt, form_values={})
