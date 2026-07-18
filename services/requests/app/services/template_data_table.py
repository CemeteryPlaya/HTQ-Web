"""Auto-maintained per-template data table (Lark "Управление данными" / Base).

Each template owns a ``RequestReferenceSource`` (``template_id`` set) whose
columns mirror the form (metadata + fillable fields) and whose rows mirror the
template's instances. Rows are upserted on every instance change, keyed by
``instance_id``. Because it's a reference source, it can also feed
"Data from Base" dropdowns in other forms.
"""

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.approval_action import ApprovalAction
from app.models.form_template import RequestFormTemplate, RequestFormTemplateVersion
from app.models.reference_source import RequestReferenceRow, RequestReferenceSource
from app.models.request_instance import RequestInstance
from app.models.user_replica import RequestUser

# Fixed metadata columns (left-to-right order), Lark parity.
COL_CODE = "Номер запроса"
COL_STATUS = "Статус"
COL_SUBMITTED = "Отправлено"
COL_COMPLETED = "Завершено"
COL_INITIATOR = "Инициатор"
COL_ASSIGNEE = "Текущий согласующий"
META_COLS = [COL_CODE, COL_STATUS, COL_SUBMITTED, COL_COMPLETED, COL_INITIATOR, COL_ASSIGNEE]

STATUS_RU = {
    "draft": "Черновик", "pending": "На рассмотрении", "approved": "Одобрено",
    "rejected": "Отклонено", "cancelled": "Отменено", "returned": "Возвращено",
}

# Widgets that carry no fillable value → not a data column.
_SKIP_TYPES = {"static_text"}


def _field_columns(schema: dict | None) -> list[str]:
    cols: list[str] = []
    for f in (schema or {}).get("fields", []):
        if f.get("type") in _SKIP_TYPES:
            continue
        cols.append(f.get("label") or f.get("key") or "")
    return [c for c in cols if c]


async def ensure_source_for_template(
    session: AsyncSession, template: RequestFormTemplate
) -> RequestReferenceSource:
    """Return the template's data-table source, creating it (metadata columns
    only) on first call."""
    existing = (await session.execute(
        select(RequestReferenceSource).where(RequestReferenceSource.template_id == template.id)
    )).scalar_one_or_none()
    if existing:
        return existing
    src = RequestReferenceSource(
        slug=f"tpl-{template.id}",
        name=template.name,
        template_id=template.id,
        columns_json=list(META_COLS),
        created_by=template.created_by,
    )
    session.add(src)
    await session.flush()
    return src


async def sync_columns_for_template(
    session: AsyncSession, template: RequestFormTemplate, schema: dict | None
) -> None:
    """Recompute the data-table columns from the form schema (metadata + fields).
    Called when a version is published (i.e. the form changed)."""
    src = await ensure_source_for_template(session, template)
    src.columns_json = list(META_COLS) + _field_columns(schema)
    src.name = template.name
    await session.flush()


async def _username(session: AsyncSession, uid: int | None) -> str:
    if uid is None:
        return ""
    u = await session.get(RequestUser, uid)
    return u.username if (u and u.username) else f"ID {uid}"


def _render(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, dict) and "amount" in v:
        amt, cur = v.get("amount"), v.get("currency", "")
        return f"{amt} {cur}".strip() if amt is not None else ""
    if isinstance(v, list):
        return ", ".join(_render(x) for x in v)
    if isinstance(v, bool):
        return "да" if v else "нет"
    return str(v)


async def _template_admins(session: AsyncSession, source: RequestReferenceSource) -> tuple[int | None, list[int]]:
    """(template creator, process_admin_ids) for a template-linked source."""
    if source.template_id is None:
        return None, []
    tpl = await session.get(RequestFormTemplate, source.template_id)
    if tpl is None:
        return None, []
    admins = (tpl.config_json or {}).get("process_admin_ids") or []
    return tpl.created_by, [int(a) for a in admins if isinstance(a, int)]


async def can_manage_data_table(session: AsyncSession, source: RequestReferenceSource, user_id: int, is_elevated: bool) -> bool:
    """Owner-level: template creator, a process admin, or a platform admin. May
    grant/revoke viewers."""
    if is_elevated:
        return True
    if source.template_id is None:
        return False
    creator, admins = await _template_admins(session, source)
    return user_id == creator or user_id in admins


async def can_view_data_table(session: AsyncSession, source: RequestReferenceSource, user_id: int, is_elevated: bool) -> bool:
    """Managers plus explicitly-granted viewers (`access_ids`)."""
    if await can_manage_data_table(session, source, user_id, is_elevated):
        return True
    return user_id in [int(x) for x in (source.access_ids or []) if isinstance(x, int)]


async def sync_row_for_instance(session: AsyncSession, inst: RequestInstance) -> None:
    """Upsert the data-table row mirroring ``inst``. No-op for templates that
    have no data table (e.g. created before this feature)."""
    src = (await session.execute(
        select(RequestReferenceSource).where(RequestReferenceSource.template_id == inst.template_id)
    )).scalar_one_or_none()
    if src is None:
        return

    version = (
        await session.get(RequestFormTemplateVersion, inst.template_version_id)
        if inst.template_version_id else None
    )
    schema = version.schema_json if version else {}
    fv = inst.form_values_json or {}

    # current assignees = unacted approvers on the current node
    assignee = ""
    if inst.current_node_id:
        ids = (await session.execute(
            select(ApprovalAction.approver_id).where(
                ApprovalAction.request_id == inst.id,
                ApprovalAction.node_id == inst.current_node_id,
                ApprovalAction.acted_at.is_(None),
            )
        )).scalars().all()
        names = [await _username(session, a) for a in ids]
        assignee = ", ".join(n for n in names if n)

    data: dict[str, str] = {
        COL_CODE: inst.code,
        COL_STATUS: STATUS_RU.get(inst.status, inst.status),
        COL_SUBMITTED: inst.submitted_at.isoformat() if inst.submitted_at else "",
        COL_COMPLETED: inst.finalized_at.isoformat() if inst.finalized_at else "",
        COL_INITIATOR: await _username(session, inst.initiator_id),
        COL_ASSIGNEE: assignee,
    }
    for f in (schema or {}).get("fields", []):
        if f.get("type") in _SKIP_TYPES:
            continue
        col = f.get("label") or f.get("key") or ""
        if col:
            data[col] = _render(fv.get(f.get("key")))

    row = (await session.execute(
        select(RequestReferenceRow).where(RequestReferenceRow.instance_id == inst.id)
    )).scalar_one_or_none()
    if row is None:
        session.add(RequestReferenceRow(source_id=src.id, instance_id=inst.id, data_json=data))
    else:
        row.data_json = data
    await session.flush()
