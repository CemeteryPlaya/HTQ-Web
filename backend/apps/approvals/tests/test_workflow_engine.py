"""Unit tests for the pure workflow layer.

PLAN.md §6.2 calls the workflow engine "самая ценная логика, переносить с
юнит-тестами 1:1" — so these exercise the graph validator, the JsonLogic
evaluator and the traversal directly, with no DB and no HTTP. If a later
refactor breaks routing, it should fail here first, in a test that names the
rule rather than in an end-to-end approval scenario.
"""

import pytest
from pydantic import ValidationError

from apps.approvals.services.condition_eval import evaluate, evaluate_raw
from apps.approvals.services.workflow_engine import (
    WorkflowError, build_runtime, first_actionable, next_actionable,
    resolve_outcome,
)
from apps.approvals.services.workflow_schema import (
    extract_var_refs, validate_workflow,
)


def _graph(nodes, edges) -> dict:
    return {"nodes": nodes, "edges": edges}


LINEAR = _graph(
    [
        {"id": "s", "type": "start"},
        {"id": "a1", "type": "approval", "assignee": {"kind": "user", "id": 1}},
        {"id": "ok", "type": "end_approved"},
        {"id": "no", "type": "end_rejected"},
    ],
    [
        {"from": "s", "to": "a1"},
        {"from": "a1", "to": "ok", "on": "approve"},
        {"from": "a1", "to": "no", "on": "reject"},
    ],
)


# ── graph validation ────────────────────────────────────────────────────

def test_valid_graph_parses():
    graph = validate_workflow(LINEAR)
    assert {n.id for n in graph.nodes} == {"s", "a1", "ok", "no"}
    # ``from`` is a Python keyword — the alias must survive the port.
    assert graph.edges[0].from_ == "s"


@pytest.mark.parametrize("mutation,message", [
    ({"nodes": [{"id": "s", "type": "start"}], "edges": []},
     "at least one end node"),
    ({"nodes": [{"id": "ok", "type": "end_approved"}], "edges": []},
     "exactly one start node"),
])
def test_graph_requires_a_start_and_an_end(mutation, message):
    with pytest.raises(ValidationError) as exc:
        validate_workflow(mutation)
    assert message in str(exc.value)


def test_duplicate_node_ids_are_rejected():
    bad = _graph([{"id": "s", "type": "start"}, {"id": "s", "type": "end_approved"}],
                 [])
    with pytest.raises(ValidationError) as exc:
        validate_workflow(bad)
    assert "duplicate node ids" in str(exc.value)


def test_dangling_edge_is_rejected():
    bad = _graph(
        [{"id": "s", "type": "start"}, {"id": "ok", "type": "end_approved"}],
        [{"from": "s", "to": "nowhere"}],
    )
    with pytest.raises(ValidationError) as exc:
        validate_workflow(bad)
    assert "unknown node" in str(exc.value)


def test_cycle_is_rejected_at_publish_time():
    """The acyclicity check is what lets the runtime trust its traversal."""
    bad = _graph(
        [{"id": "s", "type": "start"},
         {"id": "a", "type": "approval", "assignee": {"kind": "user", "id": 1}},
         {"id": "b", "type": "approval", "assignee": {"kind": "user", "id": 2}},
         {"id": "ok", "type": "end_approved"}],
        [{"from": "s", "to": "a"},
         {"from": "a", "to": "b", "on": "approve"},
         {"from": "b", "to": "a", "on": "approve"},
         {"from": "a", "to": "ok", "on": "reject"}],
    )
    with pytest.raises(ValidationError) as exc:
        validate_workflow(bad)
    assert "cycle" in str(exc.value)


def test_acknowledge_node_requires_an_assignee():
    bad = _graph(
        [{"id": "s", "type": "start"}, {"id": "ack", "type": "acknowledge"},
         {"id": "ok", "type": "end_approved"}],
        [{"from": "s", "to": "ack"}, {"from": "ack", "to": "ok"}],
    )
    with pytest.raises(ValidationError) as exc:
        validate_workflow(bad)
    assert "requires an assignee" in str(exc.value)


def test_extract_var_refs_walks_nested_expressions():
    expr = {"and": [{">": [{"var": "amount"}, 100]},
                    {"==": [{"var": "dept.code"}, "IT"]}]}
    assert extract_var_refs(expr) == {"amount", "dept"}


# ── traversal ───────────────────────────────────────────────────────────

def test_first_actionable_walks_through_passive_nodes():
    graph = _graph(
        [{"id": "s", "type": "start"}, {"id": "n", "type": "notify"},
         {"id": "a1", "type": "approval", "assignee": {"kind": "user", "id": 1}},
         {"id": "ok", "type": "end_approved"}],
        [{"from": "s", "to": "n"}, {"from": "n", "to": "a1"},
         {"from": "a1", "to": "ok", "on": "approve"}],
    )
    kind, node = first_actionable(build_runtime(graph))
    assert (kind, node.id) == ("approval", "a1")


def test_condition_node_picks_the_branch_from_form_values():
    graph = _graph(
        [{"id": "s", "type": "start"},
         {"id": "c", "type": "condition",
          "expr": {">": [{"var": "amount"}, 1000]}},
         {"id": "big", "type": "approval",
          "assignee": {"kind": "user", "id": 1}},
         {"id": "ok", "type": "end_approved"}],
        [{"from": "s", "to": "c"},
         {"from": "c", "to": "big", "when": "true"},
         {"from": "c", "to": "ok", "when": "false"},
         {"from": "big", "to": "ok", "on": "approve"}],
    )
    rt = build_runtime(graph)
    assert first_actionable(rt, form_values={"amount": 5000})[1].id == "big"
    # cheap request skips the approval entirely and lands on the end node
    kind, node = first_actionable(rt, form_values={"amount": 10})
    assert (kind, node.type) == ("end", "end_approved")


def test_missing_variable_takes_the_false_branch_rather_than_raising():
    """A half-filled form must not crash the engine mid-route."""
    graph = _graph(
        [{"id": "s", "type": "start"},
         {"id": "c", "type": "condition",
          "expr": {">": [{"var": "amount"}, 1000]}},
         {"id": "a", "type": "approval", "assignee": {"kind": "user", "id": 1}},
         {"id": "ok", "type": "end_approved"}],
        [{"from": "s", "to": "c"}, {"from": "c", "to": "a", "when": "true"},
         {"from": "c", "to": "ok", "when": "false"},
         {"from": "a", "to": "ok", "on": "approve"}],
    )
    assert first_actionable(build_runtime(graph), form_values={})[0] == "end"


def test_next_actionable_follows_the_labelled_edge():
    rt = build_runtime(LINEAR)
    assert next_actionable(rt, "a1", "approve")[1].type == "end_approved"
    assert next_actionable(rt, "a1", "reject")[1].type == "end_rejected"


def test_ambiguous_edges_are_a_workflow_error():
    graph = _graph(
        [{"id": "s", "type": "start"},
         {"id": "a", "type": "approval", "assignee": {"kind": "user", "id": 1}},
         {"id": "ok", "type": "end_approved"},
         {"id": "ok2", "type": "end_approved"}],
        [{"from": "s", "to": "a"},
         {"from": "a", "to": "ok", "on": "approve"},
         {"from": "a", "to": "ok2", "on": "approve"}],
    )
    with pytest.raises(WorkflowError) as exc:
        next_actionable(build_runtime(graph), "a", "approve")
    assert "exactly one edge" in str(exc.value)


def test_condition_without_an_expression_is_a_workflow_error():
    graph = _graph(
        [{"id": "s", "type": "start"}, {"id": "c", "type": "condition"},
         {"id": "ok", "type": "end_approved"}],
        [{"from": "s", "to": "c"}, {"from": "c", "to": "ok", "when": "true"}],
    )
    with pytest.raises(WorkflowError) as exc:
        first_actionable(build_runtime(graph))
    assert "has no expr" in str(exc.value)


# ── outcome resolution ──────────────────────────────────────────────────

@pytest.mark.parametrize("mode,actions,total,expected", [
    ("any", [], 2, None),
    ("any", [("approve", 1)], 2, "approve"),
    ("any", [("reject", 1)], 2, "reject"),
    ("all", [("approve", 1)], 2, None),
    ("all", [("approve", 1), ("approve", 2)], 2, "approve"),
    ("all", [("approve", 1), ("reject", 2)], 2, "reject"),
    # A reject decides the node whatever the mode — the safe ordering.
    ("any", [("approve", 1), ("reject", 2)], 2, "reject"),
])
def test_resolve_outcome(mode, actions, total, expected):
    assert resolve_outcome(mode, actions, total=total) == expected


# ── JsonLogic ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("expr,values,expected", [
    ({">": [{"var": "a"}, 1]}, {"a": 2}, True),
    ({"<": [{"var": "a"}, 1]}, {"a": 2}, False),
    ({"==": [{"var": "a"}, "x"]}, {"a": "x"}, True),
    ({"!=": [{"var": "a"}, "x"]}, {"a": "y"}, True),
    ({"and": [True, {"var": "a"}]}, {"a": True}, True),
    ({"or": [False, {"var": "a"}]}, {"a": False}, False),
    ({"!": [{"var": "a"}]}, {"a": False}, True),
    ({"in": [{"var": "a"}, ["x", "y"]]}, {"a": "x"}, True),
    # dot-path and list indexing
    ({"==": [{"var": "items.0.price"}, 5]}, {"items": [{"price": 5}]}, True),
    # numeric coercion across string/number, as JsonLogic specifies
    ({"==": [{"var": "a"}, 1]}, {"a": "1"}, True),
    # missing variable compares false rather than raising
    ({">": [{"var": "missing"}, 1]}, {}, False),
])
def test_evaluate(expr, values, expected):
    assert evaluate(expr, values) is expected


@pytest.mark.parametrize("expr,values,expected", [
    ({"+": [1, 2, 3]}, {}, 6.0),
    ({"-": [10, 3]}, {}, 7.0),
    ({"*": [2, 3]}, {}, 6.0),
    ({"/": [10, 4]}, {}, 2.5),
    ({"/": [1, 0]}, {}, None),          # division by zero is None, not a crash
    ({"if": [False, "a", True, "b", "c"]}, {}, "b"),
    ({"unknown_op": [1]}, {}, None),
])
def test_evaluate_raw(expr, values, expected):
    assert evaluate_raw(expr, values) == expected


def test_multi_key_op_dict_is_invalid_per_the_spec():
    assert evaluate_raw({">": [1, 0], "<": [0, 1]}, {}) is None
