"""Combined validation of a template version (schema + workflow + cross-refs)."""

from app.services.form_schema import FormSchema, validate_form_schema
from app.services.workflow_schema import (
    WorkflowGraph,
    extract_var_refs,
    validate_workflow,
)


def validate_template_version(schema_json: dict, workflow_json: dict) -> tuple[FormSchema, WorkflowGraph]:
    """Validate both blobs and their cross-references.

    Raises pydantic.ValidationError or ValueError on any problem.
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
                    f"condition node '{node.id}' references unknown field(s): {sorted(unknown)}"
                )
    return schema, graph
