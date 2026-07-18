"""Pure workflow-graph traversal for the runtime engine.

Phase 3a handles start / approval / notify / end nodes. Condition nodes raise
WorkflowError (JsonLogic evaluation lands in Phase 4)."""

from __future__ import annotations

from app.services.workflow_schema import WorkflowGraph, WorkflowNode, validate_workflow

PASSIVE = {"start", "notify"}
END = {"end_approved", "end_rejected"}


class WorkflowError(Exception):
    pass


class Runtime:
    def __init__(self, graph: WorkflowGraph):
        self.graph = graph
        self.nodes: dict[str, WorkflowNode] = {n.id: n for n in graph.nodes}

    def outgoing(self, node_id: str):
        return [e for e in self.graph.edges if e.from_ == node_id]

    def edge_for(self, node_id: str, *, on: str | None = None) -> str:
        """Pick the single target node id for a transition.

        For passive nodes (one unconditional edge) ``on`` is None. For approval
        nodes pass on='approve'|'reject' to select the labelled edge."""
        edges = self.outgoing(node_id)
        if on is None:
            unlabeled = [e for e in edges if e.on is None and e.when is None]
            if len(unlabeled) != 1:
                raise WorkflowError(
                    f"node '{node_id}' must have exactly one outgoing edge, got {len(unlabeled)}"
                )
            return unlabeled[0].to
        match = [e for e in edges if e.on == on]
        if len(match) != 1:
            raise WorkflowError(f"node '{node_id}' needs exactly one edge on='{on}', got {len(match)}")
        return match[0].to


def build_runtime(workflow_json: dict) -> Runtime:
    return Runtime(validate_workflow(workflow_json))


def _walk_to_actionable(
    rt: Runtime, node_id: str, *, form_values: dict | None = None,
) -> tuple[str, WorkflowNode]:
    """Follow passive + condition nodes from ``node_id`` until an approval or end node."""
    from app.services.condition_eval import evaluate

    seen = 0
    current = node_id
    while True:
        seen += 1
        if seen > 64:
            raise WorkflowError("workflow traversal exceeded 64 hops")
        node = rt.nodes.get(current)
        if node is None:
            raise WorkflowError(f"unknown node '{current}'")
        if node.type == "approval":
            return "approval", node
        if node.type in END:
            return "end", node
        if node.type == "condition":
            if not node.expr:
                raise WorkflowError(f"condition node '{node.id}' has no expr")
            outcome = "true" if evaluate(node.expr, form_values or {}) else "false"
            matches = [e for e in rt.outgoing(node.id) if e.when == outcome]
            if len(matches) != 1:
                raise WorkflowError(
                    f"condition node '{node.id}' needs one edge when='{outcome}', got {len(matches)}"
                )
            current = matches[0].to
            continue
        if node.type in PASSIVE:
            current = rt.edge_for(current)
            continue
        raise WorkflowError(f"unexpected node type '{node.type}'")


def first_actionable(
    rt: Runtime, *, form_values: dict | None = None,
) -> tuple[str, WorkflowNode]:
    start = next((n for n in rt.graph.nodes if n.type == "start"), None)
    if start is None:
        raise WorkflowError("workflow has no start node")
    return _walk_to_actionable(rt, rt.edge_for(start.id), form_values=form_values)


def next_actionable(
    rt: Runtime, approval_node_id: str, outcome: str, *, form_values: dict | None = None,
) -> tuple[str, WorkflowNode]:
    target = rt.edge_for(approval_node_id, on=outcome)
    return _walk_to_actionable(rt, target, form_values=form_values)


def resolve_outcome(mode: str, actions: list[tuple[str, int]], total: int | None = None) -> str | None:
    """Given (action, approver_id) tuples on a node, return 'approve'/'reject'/None.

    - any: first reject → reject; first approve → approve; else None.
    - all: any reject → reject; all `total` approved → approve; else None.
    """
    acted = [a for a, _ in actions]
    if "reject" in acted:
        return "reject"
    if mode == "any":
        return "approve" if "approve" in acted else None
    # mode == all
    approvals = [a for a in acted if a == "approve"]
    if total is not None and len(approvals) >= total:
        return "approve"
    return None
