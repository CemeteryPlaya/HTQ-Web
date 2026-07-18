"""Pydantic models + structural validation of a template's ``workflow_json``."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

NodeType = Literal[
    "start", "approval", "condition", "notify", "acknowledge", "parallel",
    "end_approved", "end_rejected",
]
END_TYPES = {"end_approved", "end_rejected"}


class WorkflowNode(BaseModel):
    id: str = Field(..., min_length=1, max_length=64)
    type: NodeType
    assignee: dict[str, Any] | None = None
    mode: Literal["any", "all", "sequential"] | None = None
    expr: dict[str, Any] | None = None
    cc: list[dict[str, Any]] | None = None


class WorkflowEdge(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    from_: str = Field(..., alias="from", min_length=1)
    to: str = Field(..., min_length=1)
    on: Literal["approve", "reject"] | None = None
    when: Literal["true", "false"] | None = None


class WorkflowGraph(BaseModel):
    nodes: list[WorkflowNode]
    edges: list[WorkflowEdge]

    @model_validator(mode="after")
    def _structure(self) -> "WorkflowGraph":
        ids = [n.id for n in self.nodes]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate node ids in workflow")
        id_set = set(ids)

        starts = [n for n in self.nodes if n.type == "start"]
        if len(starts) != 1:
            raise ValueError("workflow must have exactly one start node")
        if not any(n.type in END_TYPES for n in self.nodes):
            raise ValueError("workflow must have at least one end node")

        for e in self.edges:
            if e.from_ not in id_set:
                raise ValueError(f"edge from unknown node '{e.from_}'")
            if e.to not in id_set:
                raise ValueError(f"edge to unknown node '{e.to}'")

        for n in self.nodes:
            if n.type == "acknowledge" and not n.assignee:
                raise ValueError(f"acknowledge node '{n.id}' requires an assignee")

        self._assert_acyclic(id_set)
        return self

    def _assert_acyclic(self, id_set: set[str]) -> None:
        adj: dict[str, list[str]] = {nid: [] for nid in id_set}
        for e in self.edges:
            adj[e.from_].append(e.to)
        WHITE, GREY, BLACK = 0, 1, 2
        color = {nid: WHITE for nid in id_set}

        def visit(nid: str) -> None:
            color[nid] = GREY
            for nxt in adj[nid]:
                if color[nxt] == GREY:
                    raise ValueError("workflow graph contains a cycle")
                if color[nxt] == WHITE:
                    visit(nxt)
            color[nid] = BLACK

        for nid in id_set:
            if color[nid] == WHITE:
                visit(nid)


def extract_var_refs(expr: Any) -> set[str]:
    """Collect every {"var": "<field>"} reference inside a JsonLogic expr."""
    refs: set[str] = set()
    if isinstance(expr, dict):
        for op, val in expr.items():
            if op == "var":
                if isinstance(val, str):
                    refs.add(val.split(".")[0])
                elif isinstance(val, list) and val and isinstance(val[0], str):
                    refs.add(val[0].split(".")[0])
            else:
                refs |= extract_var_refs(val)
    elif isinstance(expr, list):
        for item in expr:
            refs |= extract_var_refs(item)
    return refs


def validate_workflow(data: dict) -> WorkflowGraph:
    return WorkflowGraph.model_validate(data)
