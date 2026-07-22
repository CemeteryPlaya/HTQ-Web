"""Auto-maintained per-template data table (Lark "Управление данными" / Base).

Ported from ``services/requests/app/services/template_data_table.py``.

Each template owns a ``RequestReferenceSource`` (``template_id`` set) whose
columns mirror the form and whose rows mirror its instances, upserted on every
instance change and keyed by ``instance_id``. Because it is a reference
source, it can also feed "Data from Base" dropdowns in other forms.

Р2 note: the initiator/approver columns render a display name that used to
come from the ``request_users`` replica. It now comes from
``apps.users.interface``, and when users cannot answer the original's own
fallback (``"ID <n>"``) is used — the table stays readable and the row still
identifies the person.
"""

from __future__ import annotations

from typing import Any

from apps.core.services import ServiceDisabled
from apps.users import interface as users_interface

from ..models import (
    ApprovalAction, RequestFormTemplate, RequestFormTemplateVersion,
    RequestInstance, RequestReferenceRow, RequestReferenceSource,
)

# Fixed metadata columns, left-to-right (Lark parity).
COL_CODE = "Номер запроса"
COL_STATUS = "Статус"
COL_SUBMITTED = "Отправлено"
COL_COMPLETED = "Завершено"
COL_INITIATOR = "Инициатор"
COL_ASSIGNEE = "Текущий согласующий"
META_COLS = [COL_CODE, COL_STATUS, COL_SUBMITTED, COL_COMPLETED,
             COL_INITIATOR, COL_ASSIGNEE]

STATUS_RU = {
    "draft": "Черновик", "pending": "На рассмотрении", "approved": "Одобрено",
    "rejected": "Отклонено", "cancelled": "Отменено", "returned": "Возвращено",
}

# Widgets carrying no fillable value are not data columns.
_SKIP_TYPES = {"static_text"}


def _field_columns(schema: dict | None) -> list[str]:
    cols = []
    for f in (schema or {}).get("fields", []):
        if f.get("type") in _SKIP_TYPES:
            continue
        cols.append(f.get("label") or f.get("key") or "")
    return [c for c in cols if c]


def ensure_source_for_template(template: RequestFormTemplate) -> RequestReferenceSource:
    """The template's data-table source, created with metadata columns only
    on first call."""
    existing = RequestReferenceSource.objects.filter(
        template_id=template.id).first()
    if existing is not None:
        return existing
    return RequestReferenceSource.objects.create(
        slug=f"tpl-{template.id}", name=template.name, template_id=template.id,
        columns_json=list(META_COLS), created_by=template.created_by,
    )


def sync_columns_for_template(template: RequestFormTemplate,
                              schema: dict | None) -> None:
    """Recompute the columns from the form schema. Called when a version is
    published, i.e. when the form actually changed."""
    source = ensure_source_for_template(template)
    source.columns_json = list(META_COLS) + _field_columns(schema)
    source.name = template.name
    source.save(update_fields=["columns_json", "name", "updated_at"])


def _names_for(user_ids: list[int]) -> dict[int, str]:
    """Display names, batched, with the original's ``"ID <n>"`` fallback."""
    ids = [uid for uid in user_ids if uid is not None]
    if not ids:
        return {}
    try:
        rows = users_interface.get_users_brief(ids)
    except (ServiceDisabled, NotImplementedError):
        rows = []
    except Exception:
        rows = []
    by_id = {row["id"]: (row.get("username") or "") for row in rows}
    return {uid: (by_id.get(uid) or f"ID {uid}") for uid in ids}


def _render(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, dict) and "amount" in v:
        amount, currency = v.get("amount"), v.get("currency", "")
        return f"{amount} {currency}".strip() if amount is not None else ""
    if isinstance(v, list):
        return ", ".join(_render(x) for x in v)
    if isinstance(v, bool):
        return "да" if v else "нет"
    return str(v)


def _template_admins(source: RequestReferenceSource) -> tuple[int | None, list[int]]:
    """``(template creator, process_admin_ids)`` for a template-linked source."""
    if source.template_id is None:
        return None, []
    template = RequestFormTemplate.objects.filter(pk=source.template_id).first()
    if template is None:
        return None, []
    admins = (template.config_json or {}).get("process_admin_ids") or []
    return template.created_by, [int(a) for a in admins if isinstance(a, int)]


def can_manage_data_table(source: RequestReferenceSource, user_id: int,
                          is_elevated: bool) -> bool:
    """Owner level — template creator, a process admin, or a platform admin.
    May grant and revoke viewers."""
    if is_elevated:
        return True
    if source.template_id is None:
        return False
    creator, admins = _template_admins(source)
    return user_id == creator or user_id in admins


def can_view_data_table(source: RequestReferenceSource, user_id: int,
                        is_elevated: bool) -> bool:
    """Managers, plus explicitly granted viewers (``access_ids``)."""
    if can_manage_data_table(source, user_id, is_elevated):
        return True
    return user_id in [int(x) for x in (source.access_ids or [])
                       if isinstance(x, int)]


def sync_row_for_instance(instance: RequestInstance) -> None:
    """Upsert the row mirroring ``instance``.

    A no-op for templates with no data table (e.g. created before the feature
    existed) — that is the original's behaviour and it keeps this callable
    unconditionally from the runtime.
    """
    source = RequestReferenceSource.objects.filter(
        template_id=instance.template_id).first()
    if source is None:
        return

    version = (RequestFormTemplateVersion.objects
               .filter(pk=instance.template_version_id).first()
               if instance.template_version_id else None)
    schema = version.schema_json if version else {}
    values = instance.form_values_json or {}

    assignee_ids = []
    if instance.current_node_id:
        assignee_ids = list(ApprovalAction.objects.filter(
            request=instance, node_id=instance.current_node_id,
            acted_at__isnull=True).values_list("approver_id", flat=True))

    names = _names_for([instance.initiator_id, *assignee_ids])
    data: dict[str, str] = {
        COL_CODE: instance.code,
        COL_STATUS: STATUS_RU.get(instance.status, instance.status),
        COL_SUBMITTED: (instance.submitted_at.isoformat()
                        if instance.submitted_at else ""),
        COL_COMPLETED: (instance.finalized_at.isoformat()
                        if instance.finalized_at else ""),
        COL_INITIATOR: names.get(instance.initiator_id, ""),
        COL_ASSIGNEE: ", ".join(
            n for n in (names.get(a) for a in assignee_ids) if n),
    }
    for f in (schema or {}).get("fields", []):
        if f.get("type") in _SKIP_TYPES:
            continue
        col = f.get("label") or f.get("key") or ""
        if col:
            data[col] = _render(values.get(f.get("key")))

    row = RequestReferenceRow.objects.filter(instance_id=instance.id).first()
    if row is None:
        RequestReferenceRow.objects.create(source=source,
                                           instance_id=instance.id,
                                           data_json=data)
    else:
        row.data_json = data
        row.save(update_fields=["data_json"])
