"""Submit / act / advance orchestration for request instances."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.approval_action import ApprovalAction, ApprovalActionType
from app.models.form_template import RequestFormTemplateVersion
from app.models.request_instance import RequestInstance, RequestStatus
from app.repositories.instance_repo import InstanceRepository
from app.services.assignee_resolver import AssigneeResolutionError, resolve_assignees
from app.services.dispatch import dispatch_event
from app.services.value_validation import compute_total, validate_values
from app.services.workflow_engine import (
    WorkflowError,
    build_runtime,
    first_actionable,
    next_actionable,
    resolve_outcome,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _load_version(session: AsyncSession, version_id: int) -> RequestFormTemplateVersion:
    v = await session.get(RequestFormTemplateVersion, version_id)
    if v is None:
        raise HTTPException(status_code=409, detail="template version not found")
    return v


async def _assign_node(session: AsyncSession, repo: InstanceRepository, inst: RequestInstance, node) -> None:
    """Create approval_actions for a freshly-entered approval node."""
    try:
        user_ids = await resolve_assignees(
            session, node.assignee, initiator_id=inst.initiator_id, project_id=inst.project_id,
            form_values=inst.form_values_json or {},
        )
    except AssigneeResolutionError as exc:
        inst.requires_admin_attention = True
        repo.log(inst.id, "assignee_resolution_failed", None, {"node": node.id, "error": str(exc)})
        raise HTTPException(status_code=422, detail=f"Cannot resolve approvers: {exc}")
    if not user_ids:
        inst.requires_admin_attention = True
        repo.log(inst.id, "assignee_resolution_failed", None, {"node": node.id, "error": "no approvers"})
        raise HTTPException(status_code=422, detail="No approvers resolved for the next step")

    # Approver deduplication: if everyone assigned to this node has already
    # approved earlier in the flow, auto-approve it instead of re-asking.
    from sqlalchemy import select as _select

    from app.services.template_settings import settings_for_instance
    st = await settings_for_instance(session, inst)
    if st["dedup"] in ("once_auto", "consecutive_auto"):
        prior = (await session.execute(
            _select(ApprovalAction.approver_id).where(
                ApprovalAction.request_id == inst.id,
                ApprovalAction.action == "approve",
                ApprovalAction.acted_at.is_not(None),
            )
        )).scalars().all()
        eligible = set(prior)  # once_auto: anyone who approved before
        if st["dedup"] == "consecutive_auto":
            # restrict to the immediately-preceding node's approvers
            eligible = {
                a.approver_id
                for a in await repo.live_actions(inst.id, inst.current_node_id or "")
                if a.action == "approve"
            }
        if user_ids and set(user_ids).issubset(eligible):
            inst.current_node_id = node.id
            for uid in user_ids:
                session.add(ApprovalAction(
                    request_id=inst.id, node_id=node.id, approver_id=uid,
                    action="approve", acted_at=_now(),
                ))
            await session.flush()
            repo.log(inst.id, "auto_approved_dedup", None, {"node": node.id})
            await _advance(session, repo, inst)
            return

    inst.current_node_id = node.id
    new_actions: list[ApprovalAction] = []
    for uid in user_ids:
        a = ApprovalAction(request_id=inst.id, node_id=node.id, approver_id=uid)
        session.add(a)
        new_actions.append(a)
    await session.flush()
    repo.log(inst.id, "step_assigned", None, {"node": node.id, "approvers": user_ids})
    await dispatch_event(session, inst, "request_assigned", user_ids)
    # Deferred reminders + escalation per action (no polling — Dramatiq's
    # delayed-message queue does the timing).
    from app.core.settings import settings as _settings
    from app.workers.notifications import schedule_escalation, schedule_reminder
    for a in new_actions:
        schedule_reminder.send_with_options(
            args=[a.id],
            delay=_settings.requests_reminder_after_hours * 3600 * 1000,
        )
        schedule_escalation.send_with_options(
            args=[a.id],
            delay=_settings.requests_escalation_after_hours * 3600 * 1000,
        )


async def _finalize(repo: InstanceRepository, inst: RequestInstance, end_type: str) -> None:
    inst.status = RequestStatus.APPROVED.value if end_type == "end_approved" else RequestStatus.REJECTED.value
    inst.current_node_id = None
    inst.finalized_at = _now()
    repo.log(inst.id, "finalized", None, {"result": inst.status})
    # fan-out to initiator + everyone who has acted on the request
    from sqlalchemy import select as _select
    acted_rows = (await repo.session.execute(
        _select(ApprovalAction.approver_id).where(
            ApprovalAction.request_id == inst.id, ApprovalAction.acted_at.is_not(None),
        )
    )).scalars().all()
    recipients = {inst.initiator_id, *acted_rows}
    end_kind = "approved_final" if end_type == "end_approved" else "rejected"
    await dispatch_event(repo.session, inst, end_kind, recipients)
    from app.services.stats_rollup import upsert_finalization
    await upsert_finalization(repo.session, inst)


async def submit(session: AsyncSession, inst: RequestInstance, *, actor_id: int) -> RequestInstance:
    if inst.status not in (RequestStatus.DRAFT.value, RequestStatus.RETURNED.value):
        raise HTTPException(status_code=409, detail=f"cannot submit from status '{inst.status}'")
    version = await _load_version(session, inst.template_version_id)
    try:
        validate_values(version.schema_json, inst.form_values_json or {})
        inst.total_amount = compute_total(version.schema_json, inst.form_values_json or {})
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    repo = InstanceRepository(session)
    rt = build_runtime(version.workflow_json)
    try:
        kind, node = first_actionable(rt, form_values=inst.form_values_json or {})
    except WorkflowError as exc:
        raise HTTPException(status_code=422, detail=f"Invalid workflow: {exc}")

    inst.status = RequestStatus.PENDING.value
    inst.submitted_at = _now()
    inst.requires_admin_attention = False
    repo.log(inst.id, "submitted", actor_id, None)

    if kind == "end":
        await _finalize(repo, inst, node.type)
    else:
        await _assign_node(session, repo, inst, node)
    await session.flush()
    from app.services.template_data_table import sync_row_for_instance
    await sync_row_for_instance(session, inst)
    return inst


async def act(
    session: AsyncSession, inst: RequestInstance, *, approver_id: int, action: str, comment: str = ""
) -> RequestInstance:
    if inst.status != RequestStatus.PENDING.value or not inst.current_node_id:
        raise HTTPException(status_code=409, detail="request is not awaiting approval")
    repo = InstanceRepository(session)
    mine = await repo.my_live_action(inst.id, inst.current_node_id, approver_id)
    if mine is None:
        raise HTTPException(status_code=403, detail="you are not an active approver on this step")

    if action == "request_changes":
        mine.action = ApprovalActionType.REQUEST_CHANGES.value
        mine.acted_at = _now()
        mine.comment = comment
        inst.status = RequestStatus.RETURNED.value
        inst.current_node_id = None
        repo.log(inst.id, "request_changes", approver_id, {"comment": comment})
        for a in await repo.live_actions(inst.id, mine.node_id):
            if a.acted_at is None:
                a.action = ApprovalActionType.AUTO_SKIP.value
                a.acted_at = _now()
        await dispatch_event(session, inst, "request_changes", [inst.initiator_id],
                             approver_id=approver_id, comment=comment)
        await session.flush()
        from app.services.template_data_table import sync_row_for_instance
        await sync_row_for_instance(session, inst)
        return inst

    if action not in ("approve", "reject"):
        raise HTTPException(status_code=400, detail="invalid action")
    mine.action = action
    mine.acted_at = _now()
    mine.comment = comment
    repo.log(inst.id, action, approver_id, {"comment": comment})
    if action == "reject":
        # finalize via _advance below will fan out 'rejected'; nothing extra here
        pass
    elif action == "approve" and inst.status == RequestStatus.PENDING.value and inst.current_node_id:
        # partial-approve notification: peers still pending + initiator
        peers = [
            a.approver_id
            for a in await repo.live_actions(inst.id, inst.current_node_id)
            if a.acted_at is None and a.approver_id != approver_id
        ]
        if peers:
            await dispatch_event(session, inst, "approved_partial", [*peers, inst.initiator_id],
                                 approver_id=approver_id)
    await _advance(session, repo, inst)
    await session.flush()
    from app.services.template_data_table import sync_row_for_instance
    await sync_row_for_instance(session, inst)
    return inst


async def _advance(session: AsyncSession, repo: InstanceRepository, inst: RequestInstance) -> None:
    version = await _load_version(session, inst.template_version_id)
    rt = build_runtime(version.workflow_json)
    node = rt.nodes[inst.current_node_id]
    mode = node.mode or "any"
    all_actions = await repo.live_actions(inst.id, inst.current_node_id)
    acted = [
        (a.action, a.approver_id)
        for a in all_actions
        if a.acted_at is not None and a.action in ("approve", "reject")
    ]
    total = len(all_actions)
    outcome = resolve_outcome(mode, acted, total=total)
    if outcome is None:
        return
    for a in all_actions:
        if a.acted_at is None:
            a.action = ApprovalActionType.AUTO_SKIP.value
            a.acted_at = _now()
    kind, nxt = next_actionable(rt, inst.current_node_id, outcome,
                                 form_values=inst.form_values_json or {})
    if kind == "end":
        await _finalize(repo, inst, nxt.type)
    else:
        await _assign_node(session, repo, inst, nxt)


async def cancel(
    session: AsyncSession, inst: RequestInstance, *, actor_id: int, is_elevated: bool
) -> RequestInstance:
    if actor_id != inst.initiator_id and not is_elevated:
        raise HTTPException(status_code=403, detail="only the initiator or an admin can cancel")

    from sqlalchemy import select

    from app.services.template_settings import settings_for_instance
    st = await settings_for_instance(session, inst)

    if inst.status in (RequestStatus.REJECTED.value, RequestStatus.CANCELLED.value):
        raise HTTPException(status_code=409, detail=f"cannot cancel a {inst.status} request")

    if inst.status == RequestStatus.APPROVED.value:
        ok = (
            st["allow_revoke_within_days"]
            and inst.finalized_at is not None
            and (
                _now()
                - (inst.finalized_at if inst.finalized_at.tzinfo else inst.finalized_at.replace(tzinfo=timezone.utc))
            ).days <= int(st["revoke_within_days"] or 0)
        )
        if not (ok or is_elevated):
            raise HTTPException(status_code=409, detail="cannot cancel an approved request")
    elif inst.status == RequestStatus.PENDING.value and not st["allow_revoke_pending"] and not is_elevated:
        approved_before = (await session.execute(
            select(ApprovalAction).where(
                ApprovalAction.request_id == inst.id,
                ApprovalAction.action == "approve",
                ApprovalAction.acted_at.is_not(None),
            )
        )).first()
        if approved_before:
            raise HTTPException(status_code=409, detail="revoking after the first approval step is disabled")
    repo = InstanceRepository(session)
    live = await repo.live_actions(inst.id, inst.current_node_id or "")
    recipients = {a.approver_id for a in live if a.acted_at is None}
    inst.status = RequestStatus.CANCELLED.value
    inst.current_node_id = None
    inst.finalized_at = _now()
    repo.log(inst.id, "cancelled", actor_id, None)
    if recipients:
        await dispatch_event(session, inst, "cancelled", recipients, actor_id=actor_id)
    from app.services.stats_rollup import upsert_finalization
    await upsert_finalization(session, inst)
    await session.flush()
    from app.services.template_data_table import sync_row_for_instance
    await sync_row_for_instance(session, inst)
    return inst


async def recall(
    session: AsyncSession, inst: RequestInstance, *, approver_id: int
) -> RequestInstance:
    """Reverse this approver's own ``approve`` and move the request back to that
    step. Allowed only when the template opts in via ``allow_recall_decision``,
    the request is not finalized as rejected/cancelled, and *no later step has
    been acted on yet*."""
    from sqlalchemy import select as _select

    from app.services.template_settings import settings_for_instance
    st = await settings_for_instance(session, inst)
    if not st["allow_recall_decision"]:
        raise HTTPException(status_code=403, detail="recalling a decision is not allowed for this request")

    if inst.status in (RequestStatus.REJECTED.value, RequestStatus.CANCELLED.value):
        raise HTTPException(status_code=409, detail=f"cannot recall on a {inst.status} request")

    repo = InstanceRepository(session)
    # This approver's most recent *acted* approval (its node is where we return).
    mine = (await session.execute(
        _select(ApprovalAction)
        .where(
            ApprovalAction.request_id == inst.id,
            ApprovalAction.approver_id == approver_id,
            ApprovalAction.action == ApprovalActionType.APPROVE.value,
            ApprovalAction.acted_at.is_not(None),
        )
        .order_by(ApprovalAction.id.desc())
    )).scalars().first()
    if mine is None:
        raise HTTPException(status_code=409, detail="you have no approval to recall on this request")
    node = mine.node_id

    # Slots auto-created once the flow advanced past ``node`` (later steps). Using
    # ``id > mine.id`` keeps same-node peers (created alongside ``mine``) out of it.
    downstream = (await session.execute(
        _select(ApprovalAction).where(
            ApprovalAction.request_id == inst.id,
            ApprovalAction.node_id != node,
            ApprovalAction.id > mine.id,
        )
    )).scalars().all()
    if any(
        a.acted_at is not None and a.action not in (None, ApprovalActionType.AUTO_SKIP.value)
        for a in downstream
    ):
        raise HTTPException(status_code=409, detail="a later step has already been acted on")

    # Drop the downstream slots so re-approval re-creates them cleanly.
    for a in downstream:
        await session.delete(a)

    # Reset this approver's slot back to live.
    mine.action = None
    mine.acted_at = None
    mine.comment = ""

    # Un-skip peers on this node that were AUTO_SKIP'd when it advanced.
    for a in await repo.live_actions(inst.id, node):
        if a.id != mine.id and a.action == ApprovalActionType.AUTO_SKIP.value:
            a.action = None
            a.acted_at = None
            a.comment = ""

    inst.status = RequestStatus.PENDING.value
    inst.current_node_id = node
    inst.finalized_at = None
    repo.log(inst.id, "recalled", approver_id, {"node": node})
    await session.flush()
    from app.services.template_data_table import sync_row_for_instance
    await sync_row_for_instance(session, inst)
    return inst


async def handle_user_deactivated(session: AsyncSession, user_id: int) -> int:
    """Auto-skip every live approval slot held by ``user_id`` and re-advance
    the affected requests. Returns the number of requests touched.

    Called from the Redis replica-sync subscriber when ``user.deactivated``
    arrives. Idempotent — re-running has no effect once actions are skipped."""
    from sqlalchemy import select as _select

    repo = InstanceRepository(session)
    stmt = _select(ApprovalAction).where(
        ApprovalAction.approver_id == user_id, ApprovalAction.acted_at.is_(None)
    )
    live_actions = list((await session.execute(stmt)).scalars().all())
    touched: set[int] = set()
    for a in live_actions:
        a.action = ApprovalActionType.AUTO_SKIP.value
        a.acted_at = _now()
        touched.add(a.request_id)
    await session.flush()

    for req_id in touched:
        inst = await session.get(RequestInstance, req_id)
        if inst is None or inst.status != RequestStatus.PENDING.value or not inst.current_node_id:
            continue
        inst.requires_admin_attention = True
        repo.log(inst.id, "approver_deactivated", None, {"user_id": user_id})
        # Re-advance — if the node had other live approvers the request keeps
        # waiting on them; if everyone on the node is now auto_skipped the
        # outcome stays unresolved and the request just sits with the admin-
        # attention flag set. A finer fallback (auto-reject after timeout)
        # can land later.
        try:
            await _advance(session, repo, inst)
        except Exception as exc:  # noqa: BLE001
            # Don't let one broken workflow block the rest of the batch.
            repo.log(inst.id, "advance_failed_after_deactivation", None, {"error": str(exc)})
    await session.flush()
    return len(touched)
