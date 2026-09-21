"""Validation of a template version — the form schema.

Маршрут согласования больше не часть версии: он живёт в ``apps.signoff``
(маршрут по области ``template:<id>``) и правится отдельно от формы. Поэтому
проверяется только ``schema_json``. ``workflow_json`` старых версий и
клиентов принимается и, если непуст, проверяется как прежде — ради истории
(его читает конвертер ``migrate_workflows_to_signoff``) и старых тестов, но
на исполнение он не влияет.
"""

from __future__ import annotations

from .form_schema import FormSchema, validate_form_schema
from .workflow_schema import (
    WorkflowGraph,
    extract_var_refs,
    validate_workflow,
)


def validate_template_version(schema_json: dict,
                              workflow_json: dict | None = None,
                              ) -> tuple[FormSchema, WorkflowGraph | None]:
    """Validate the schema and, when a legacy workflow is supplied, its
    cross-references.

    Raises ``pydantic.ValidationError`` or ``ValueError`` on any problem; the
    view maps both to 422.
    """
    schema = validate_form_schema(schema_json)
    if not workflow_json:
        return schema, None

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
