import pytest

from app.services.template_validation import validate_template_version
from app.services.workflow_schema import validate_workflow

_SCHEMA = {"fields": [
    {"type": "money", "key": "amount", "label": "Сумма", "contributes_to_total": True},
]}

_GOOD_WF = {
    "nodes": [
        {"id": "n_start", "type": "start"},
        {"id": "n_pm", "type": "approval", "assignee": {"kind": "project_admins"}, "mode": "any"},
        {"id": "n_cond", "type": "condition", "expr": {">": [{"var": "amount"}, 100000]}},
        {"id": "n_fin", "type": "approval", "assignee": {"kind": "user", "id": 42}, "mode": "all"},
        {"id": "n_ok", "type": "end_approved"},
        {"id": "n_no", "type": "end_rejected"},
    ],
    "edges": [
        {"from": "n_start", "to": "n_pm"},
        {"from": "n_pm", "to": "n_cond", "on": "approve"},
        {"from": "n_pm", "to": "n_no", "on": "reject"},
        {"from": "n_cond", "to": "n_fin", "when": "true"},
        {"from": "n_cond", "to": "n_ok", "when": "false"},
        {"from": "n_fin", "to": "n_ok", "on": "approve"},
        {"from": "n_fin", "to": "n_no", "on": "reject"},
    ],
}


def test_valid_template_version():
    schema, graph = validate_template_version(_SCHEMA, _GOOD_WF)
    assert schema.keys == {"amount"}
    assert len(graph.nodes) == 6


def test_edge_to_missing_node_rejected():
    wf = {"nodes": [{"id": "n_start", "type": "start"}, {"id": "n_ok", "type": "end_approved"}],
          "edges": [{"from": "n_start", "to": "ghost"}]}
    with pytest.raises(ValueError):
        validate_template_version(_SCHEMA, wf)


def test_requires_exactly_one_start():
    wf = {"nodes": [{"id": "a", "type": "approval"}, {"id": "e", "type": "end_approved"}],
          "edges": [{"from": "a", "to": "e"}]}
    with pytest.raises(ValueError):
        validate_template_version(_SCHEMA, wf)


def test_requires_an_end_node():
    wf = {"nodes": [{"id": "n_start", "type": "start"}, {"id": "a", "type": "approval"}],
          "edges": [{"from": "n_start", "to": "a"}]}
    with pytest.raises(ValueError):
        validate_template_version(_SCHEMA, wf)


def test_cycle_rejected():
    wf = {"nodes": [
            {"id": "n_start", "type": "start"},
            {"id": "a", "type": "approval"},
            {"id": "b", "type": "approval"},
            {"id": "e", "type": "end_approved"}],
          "edges": [
            {"from": "n_start", "to": "a"},
            {"from": "a", "to": "b"},
            {"from": "b", "to": "a"},
            {"from": "a", "to": "e"}]}
    with pytest.raises(ValueError):
        validate_template_version(_SCHEMA, wf)


def test_condition_referencing_unknown_field_rejected():
    wf = {"nodes": [
            {"id": "n_start", "type": "start"},
            {"id": "c", "type": "condition", "expr": {">": [{"var": "ghost"}, 1]}},
            {"id": "ok", "type": "end_approved"},
            {"id": "no", "type": "end_rejected"}],
          "edges": [
            {"from": "n_start", "to": "c"},
            {"from": "c", "to": "ok", "when": "true"},
            {"from": "c", "to": "no", "when": "false"}]}
    with pytest.raises(ValueError):
        validate_template_version(_SCHEMA, wf)


def test_duplicate_node_ids_rejected():
    wf = {"nodes": [
            {"id": "n_start", "type": "start"},
            {"id": "dup", "type": "approval"},
            {"id": "dup", "type": "end_approved"}],
          "edges": [{"from": "n_start", "to": "dup"}]}
    with pytest.raises(ValueError):
        validate_template_version(_SCHEMA, wf)


# ─── workflow v2 (Lark parity) ──────────────────────────────────────────────


def test_workflow_v2_node_types_and_cc():
    wf = {
        "nodes": [
            {"id": "s", "type": "start"},
            {"id": "a", "type": "approval", "assignee": {"kind": "user", "id": 1},
             "mode": "sequential", "cc": [{"kind": "initiator"}]},
            {"id": "ack", "type": "acknowledge", "assignee": {"kind": "role", "name": "accounting"}},
            {"id": "ntf", "type": "notify", "assignee": {"kind": "user", "id": 2}},
            {"id": "e", "type": "end_approved"},
        ],
        "edges": [
            {"from": "s", "to": "a"}, {"from": "a", "to": "ack"},
            {"from": "ack", "to": "ntf"}, {"from": "ntf", "to": "e"},
        ],
    }
    g = validate_workflow(wf)
    node_a = next(n for n in g.nodes if n.id == "a")
    assert node_a.mode == "sequential"
    assert node_a.cc == [{"kind": "initiator"}]


def test_acknowledge_node_requires_assignee():
    # `notify` may omit an assignee (legacy engine derives recipients elsewhere);
    # the new `acknowledge` node type must name who acknowledges.
    wf = {"nodes": [
            {"id": "s", "type": "start"},
            {"id": "ack", "type": "acknowledge"},
            {"id": "e", "type": "end_approved"}],
          "edges": [{"from": "s", "to": "ack"}, {"from": "ack", "to": "e"}]}
    with pytest.raises(ValueError):
        validate_workflow(wf)


def test_v2_template_validates_end_to_end():
    schema = {
        "fields": [
            {"type": "dropdown", "key": "has_contract", "label": "Наличие договора",
             "options": ["Без договора", "По договору"]},
            {"type": "group", "key": "no_contract", "label": "Без договора",
             "summarize_keys": ["amount"], "fields": [
                {"type": "text", "key": "tru", "label": "ТРУ", "required": True},
                {"type": "amount", "key": "amount", "label": "Сумма",
                 "currencies": ["KZT", "USD"], "contributes_to_total": True}]},
        ],
        "display_conditions": [
            {"target": "no_contract",
             "conditions": [{"field": "has_contract", "op": "is", "value": "Без договора"}]},
        ],
    }
    wf = {
        "nodes": [
            {"id": "s", "type": "start"},
            {"id": "a1", "type": "approval", "assignee": {"kind": "user", "id": 1},
             "mode": "any", "cc": [{"kind": "initiator"}]},
            {"id": "a2", "type": "approval", "assignee": {"kind": "role", "name": "gd"},
             "mode": "sequential"},
            {"id": "e", "type": "end_approved"},
        ],
        "edges": [
            {"from": "s", "to": "a1"}, {"from": "a1", "to": "a2", "on": "approve"},
            {"from": "a2", "to": "e", "on": "approve"},
        ],
    }
    s, g = validate_template_version(schema, wf)
    assert "no_contract" in s.all_keys
    assert len(g.nodes) == 4
