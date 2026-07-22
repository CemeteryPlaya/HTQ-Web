"""Combined validation of a template version (schema + workflow + cross-refs).

Ported from ``services/requests/app/services/template_validation.py``. The
cross-reference check is the part that matters: a condition node may only
reference form fields that actually exist, otherwise the workflow silently
takes the ``false`` branch forever at runtime (``condition_eval`` resolves an
unknown ``var`` to ``None``, which is falsy). Catching it at publish time is
the difference between "the builder told me" and "requests mysteriously skip
the manager's step".
"""

from __future__ import annotations

from .form_schema import FormSchema, validate_form_schema
from .workflow_schema import (
    WorkflowGraph,
    extract_var_refs,
    validate_workflow,
)


def validate_template_version(schema_json: dict,
                              workflow_json: dict) -> tuple[FormSchema, WorkflowGraph]:
    """Validate both blobs and their cross-references.

    Raises ``pydantic.ValidationError`` or ``ValueError`` on any problem; the
    view maps both to 422.
    """
    schema = validate_form_schema(schema_json)
    graph = validate_workflow(workflow_json)

    keys = schema.keys
    for node in graph.nodes:
        if node.type == "condition":
            if not node.expr:
                raise ValueError(f"condition node '{node.id}' requires an 'expr'")
            unknown = extract_var_refs(node.expr) - keys
            if unknown:
                raise ValueError(
                    f"condition node '{node.id}' references unknown field(s): "
                    f"{sorted(unknown)}"
                )
    return schema, graph
