"""Submit / act / advance orchestration for request instances.

Ported from ``services/requests/app/services/request_runtime.py`` — the state
machine that moves a request through its route. This is the most
behaviour-dense module in the domain, so the port keeps its structure and its
rules rather than reshaping them.

Errors are raised as ``RuntimeConflict`` / ``RuntimeRejected`` / ``Forbidden``
instead of FastAPI's ``HTTPException``; the view layer maps them to the same
409 / 422 / 403 the original returned. Keeping HTTP out of here is what lets
the Celery jobs (reminders, deactivation sweeps) call the same functions.

Two invariants worth stating because a later edit could quietly break them:

* **A node's slots are created when the node opens, one row per assignee.**
  Parallel approval, quorum and the audit trail all fall out of that. Nothing
  should ever mutate ``current_node_id`` without creating the matching rows.
* **Advancing is driven by the rows, not by the caller.** ``_advance`` reads
  every slot on the current node and asks ``resolve_outcome`` whether the node
  is decided. An approve that does not decide the node simply returns.
"""

from __future__ import annotations

import logging

from django.db import transaction
from django.utils import timezone

from ..models import (
    ApprovalAction, ApprovalActionType, RequestActivity, RequestFormTemplateVersion,
    RequestInstance, RequestStatus,
)
from .assignee_resolver import AssigneeResolutionError, resolve_assignees
from .dispatch import dispatch_event
from .template_settings import settings_for_instance
from .value_validation import compute_total, validate_values
from .workflow_engine import (
    WorkflowError, build_runtime, first_actionable, next_actionable,
    resolve_outcome,
)

logger = logging.getLogger(__name__)


class RuntimeConflict(Exception):
    """The request is not in a state where this operation makes sense (409)."""


class RuntimeRejected(Exception):
    """The operation is well-formed but cannot be carried out (422)."""


class Forbidden(Exception):
    """The caller is not allowed to do this (403)."""


def log(instance: RequestInstance, event_type: str, actor_id: int | None,
        payload: dict | None = None) -> None:
    RequestActivity.objects.create(request=instance, event_type=event_type,
                                   actor_id=actor_id, payload=payload)


def next_code(template) -> str:
    """``REQ-<slug>-<year>-0001`` — per-template, per-year running number."""
    year = timezone.now().year
    prefix = f"REQ-{template.slug}-{year}-"
    n = RequestInstance.objects.filter(template=template,
                                       code__startswith=prefix).count() + 1
    return f"{prefix}{n:04d}"


def _load_version(version_id: int) -> RequestFormTemplateVersion:
    version = RequestFormTemplateVersion.objects.filter(pk=version_id).first()
    if version is None:
        raise RuntimeConflict("template version not found")
    return version


def node_actions(instance: RequestInstance, node_id: str) -> list[ApprovalAction]:
    return list(ApprovalAction.objects.filter(request=instance,
                                              node_id=node_id).order_by("id"))


def my_live_action(instance: RequestInstance, node_id: str,
                   approver_id: int) -> ApprovalAction | None:
    return ApprovalAction.objects.filter(
        request=instance, node_id=node_id, approver_id=approver_id,
        acted_at__isnull=True).first()


# ─────────────────────────────────────────────────────────────────────────
# Entering a node
# ─────────────────────────────────────────────────────────────────────────

def _assign_node(instance: RequestInstance, node) -> None:
    """Open an approval node: resolve its approvers and create their slots."""
    try:
        user_ids = resolve_assignees(
            node.assignee, initiator_id=instance.initiator_id,
            project_id=instance.project_id,
            form_values=instance.form_values_json or {})
    except AssigneeResolutionError as exc:
        # Flag for an admin rather than silently stalling — a request with no
        # resolvable approver is stuck and somebody has to see it.
        instance.requires_admin_attention = True
        instance.save(update_fields=["requires_admin_attention", "updated_at"])
        log(instance, "assignee_resolution_failed", None,
            {"node": node.id, "error": str(exc)})
        raise RuntimeRejected(f"Cannot resolve approvers: {exc}")
    if not user_ids:
        instance.requires_admin_attention = True
        instance.save(update_fields=["requires_admin_attention", "updated_at"])
        log(instance, "assignee_resolution_failed", None,
            {"node": node.id, "error": "no approvers"})
        raise RuntimeRejected("No approvers resolved for the next step")

    # Approver de-duplication: if everyone on this node already approved
    # earlier in the route, auto-approve instead of asking them again.
    dedup = settings_for_instance(instance)["dedup"]
    if dedup in ("once_auto", "consecutive_auto"):
        if dedup == "once_auto":
            eligible = set(ApprovalAction.objects.filter(
                request=instance, action=ApprovalActionType.APPROVE,
                acted_at__isnull=False).values_list("approver_id", flat=True))
        else:
            # consecutive_auto: only the immediately preceding node counts.
            eligible = {a.approver_id for a
                        in node_actions(instance, instance.current_node_id or "")
                        if a.action == ApprovalActionType.APPROVE}
        if set(user_ids).issubset(eligible):
            instance.current_node_id = node.id
            instance.save(update_fields=["current_node_id", "updated_at"])
            now = timezone.now()
            ApprovalAction.objects.bulk_create([
                ApprovalAction(request=instance, node_id=node.id,
                               approver_id=uid,
                               action=ApprovalActionType.APPROVE, acted_at=now)
                for uid in user_ids
            ])
            log(instance, "auto_approved_dedup", None, {"node": node.id})
            _advance(instance)
            return

    instance.current_node_id = node.id
    instance.save(update_fields=["current_node_id", "updated_at"])
    ApprovalAction.objects.bulk_create([
        ApprovalAction(request=instance, node_id=node.id, approver_id=uid)
        for uid in user_ids
    ])
    log(instance, "step_assigned", None,
        {"node": node.id, "approvers": user_ids})
    dispatch_event(instance, "request_assigned", user_ids)
    # Reminders/escalation were per-action delayed Dramatiq messages. Celery's
    # beat-driven sweep in apps/approvals/tasks.py replaces them — see that
    # module for why a periodic scan beats a delayed message here.


def _finalize(instance: RequestInstance, end_type: str) -> None:
    instance.status = (RequestStatus.APPROVED if end_type == "end_approved"
                       else RequestStatus.REJECTED)
    instance.current_node_id = None
    instance.finalized_at = timezone.now()
    instance.save(update_fields=["status", "current_node_id", "finalized_at",
                                 "updated_at"])
    log(instance, "finalized", None, {"result": instance.status})

    acted = set(ApprovalAction.objects.filter(
        request=instance, acted_at__isnull=False
    ).values_list("approver_id", flat=True))
    kind = "approved_final" if end_type == "end_approved" else "rejected"
    dispatch_event(instance, kind, {instance.initiator_id, *acted})

    from .stats_rollup import upsert_finalization
    upsert_finalization(instance)


# ─────────────────────────────────────────────────────────────────────────
# Transitions
# ─────────────────────────────────────────────────────────────────────────

@transaction.atomic
def submit(instance: RequestInstance, *, actor_id: int) -> RequestInstance:
    if instance.status not in (RequestStatus.DRAFT, RequestStatus.RETURNED):
        raise RuntimeConflict(
            f"cannot submit from status '{instance.status}'")
    version = _load_version(instance.template_version_id)
    try:
        validate_values(version.schema_json, instance.form_values_json or {})
        instance.total_amount = compute_total(version.schema_json,
                                              instance.form_values_json or {})
    except ValueError as exc:
        raise RuntimeRejected(str(exc))

    try:
        runtime = build_runtime(version.workflow_json)
        kind, node = first_actionable(
            runtime, form_values=instance.form_values_json or {})
    except WorkflowError as exc:
        raise RuntimeRejected(f"Invalid workflow: {exc}")

    instance.status = RequestStatus.PENDING
    instance.submitted_at = timezone.now()
    instance.requires_admin_attention = False
    instance.save()
    log(instance, "submitted", actor_id, None)

    if kind == "end":
        _finalize(instance, node.type)
    else:
        _assign_node(instance, node)

    _sync_data_table(instance)
    instance.refresh_from_db()
    return instance


@transaction.atomic
def act(instance: RequestInstance, *, approver_id: int, action: str,
        comment: str = "") -> RequestInstance:
    if instance.status != RequestStatus.PENDING or not instance.current_node_id:
        raise RuntimeConflict("request is not awaiting approval")
    mine = my_live_action(instance, instance.current_node_id, approver_id)
    if mine is None:
        raise Forbidden("you are not an active approver on this step")

    now = timezone.now()

    if action == "request_changes":
        mine.action = ApprovalActionType.REQUEST_CHANGES
        mine.acted_at = now
        mine.comment = comment
        mine.save()
        node_id = mine.node_id
        instance.status = RequestStatus.RETURNED
        instance.current_node_id = None
        instance.save(update_fields=["status", "current_node_id", "updated_at"])
        log(instance, "request_changes", approver_id, {"comment": comment})
        # Peers on the node lose their slot — the request has left the step.
        ApprovalAction.objects.filter(request=instance, node_id=node_id,
                                      acted_at__isnull=True).update(
            action=ApprovalActionType.AUTO_SKIP, acted_at=now)
        dispatch_event(instance, "request_changes", [instance.initiator_id],
                       approver_id=approver_id, comment=comment)
        _sync_data_table(instance)
        instance.refresh_from_db()
        return instance

    if action not in ("approve", "reject"):
        raise ValueError("invalid action")

    mine.action = action
    mine.acted_at = now
    mine.comment = comment
    mine.save()
    log(instance, action, approver_id, {"comment": comment})

    if action == "approve":
        # Partial-approve ping: peers still pending, plus the initiator.
        peers = [a.approver_id for a
                 in node_actions(instance, instance.current_node_id)
                 if a.acted_at is None and a.approver_id != approver_id]
        if peers:
            dispatch_event(instance, "approved_partial",
                           [*peers, instance.initiator_id],
                           approver_id=approver_id)

    _advance(instance)
    _sync_data_table(instance)
    instance.refresh_from_db()
    return instance


def _advance(instance: RequestInstance) -> None:
    """Decide the current node from its slots and move on if it is decided."""
    version = _load_version(instance.template_version_id)
    runtime = build_runtime(version.workflow_json)
    node = runtime.nodes[instance.current_node_id]
    mode = node.mode or "any"

    all_actions = node_actions(instance, instance.current_node_id)
    acted = [(a.action, a.approver_id) for a in all_actions
             if a.acted_at is not None and a.action in ("approve", "reject")]
    outcome = resolve_outcome(mode, acted, total=len(all_actions))
    if outcome is None:
        return          # node still open — nothing to do

    now = timezone.now()
    ApprovalAction.objects.filter(request=instance,
                                  node_id=instance.current_node_id,
                                  acted_at__isnull=True).update(
        action=ApprovalActionType.AUTO_SKIP, acted_at=now)

    kind, nxt = next_actionable(runtime, instance.current_node_id, outcome,
                                form_values=instance.form_values_json or {})
    if kind == "end":
        _finalize(instance, nxt.type)
    else:
        _assign_node(instance, nxt)


@transaction.atomic
def cancel(instance: RequestInstance, *, actor_id: int,
           is_elevated: bool) -> RequestInstance:
    if actor_id != instance.initiator_id and not is_elevated:
        raise Forbidden("only the initiator or an admin can cancel")

    st = settings_for_instance(instance)
    if instance.status in (RequestStatus.REJECTED, RequestStatus.CANCELLED):
        raise RuntimeConflict(f"cannot cancel a {instance.status} request")

    if instance.status == RequestStatus.APPROVED:
        within = (st["allow_revoke_within_days"]
                  and instance.finalized_at is not None
                  and (timezone.now() - instance.finalized_at).days
                  <= int(st["revoke_within_days"] or 0))
        if not (within or is_elevated):
            raise RuntimeConflict("cannot cancel an approved request")
    elif instance.status == RequestStatus.PENDING \
            and not st["allow_revoke_pending"] and not is_elevated:
        approved_before = ApprovalAction.objects.filter(
            request=instance, action=ApprovalActionType.APPROVE,
            acted_at__isnull=False).exists()
        if approved_before:
            raise RuntimeConflict(
                "revoking after the first approval step is disabled")

    live = [a.approver_id for a
            in node_actions(instance, instance.current_node_id or "")
            if a.acted_at is None]
    instance.status = RequestStatus.CANCELLED
    instance.current_node_id = None
    instance.finalized_at = timezone.now()
    instance.save(update_fields=["status", "current_node_id", "finalized_at",
                                 "updated_at"])
    log(instance, "cancelled", actor_id, None)
    if live:
        dispatch_event(instance, "cancelled", live, actor_id=actor_id)

    from .stats_rollup import upsert_finalization
    upsert_finalization(instance)
    _sync_data_table(instance)
    instance.refresh_from_db()
    return instance


@transaction.atomic
def recall(instance: RequestInstance, *, approver_id: int) -> RequestInstance:
    """Undo this approver's own ``approve`` and return the request to that step.

    Only when the template opts in, the request is not already
    rejected/cancelled, and **no later step has been acted on** — otherwise
    un-approving would rewrite decisions other people already made on the
    strength of it.
    """
    st = settings_for_instance(instance)
    if not st["allow_recall_decision"]:
        raise Forbidden("recalling a decision is not allowed for this request")
    if instance.status in (RequestStatus.REJECTED, RequestStatus.CANCELLED):
        raise RuntimeConflict(f"cannot recall on a {instance.status} request")

    mine = ApprovalAction.objects.filter(
        request=instance, approver_id=approver_id,
        action=ApprovalActionType.APPROVE, acted_at__isnull=False,
    ).order_by("-id").first()
    if mine is None:
        raise RuntimeConflict("you have no approval to recall on this request")
    node = mine.node_id

    # Slots created after this one on OTHER nodes are the downstream steps.
    # ``id > mine.id`` keeps same-node peers (created alongside it) out.
    downstream = list(ApprovalAction.objects.filter(
        request=instance, id__gt=mine.id).exclude(node_id=node))
    if any(a.acted_at is not None
           and a.action not in (None, ApprovalActionType.AUTO_SKIP)
           for a in downstream):
        raise RuntimeConflict("a later step has already been acted on")

    ApprovalAction.objects.filter(
        id__in=[a.id for a in downstream]).delete()

    mine.action = None
    mine.acted_at = None
    mine.comment = ""
    mine.save()

    # Un-skip peers auto-skipped when the node advanced.
    ApprovalAction.objects.filter(
        request=instance, node_id=node, action=ApprovalActionType.AUTO_SKIP
    ).exclude(id=mine.id).update(action=None, acted_at=None, comment="")

    instance.status = RequestStatus.PENDING
    instance.current_node_id = node
    instance.finalized_at = None
    instance.save(update_fields=["status", "current_node_id", "finalized_at",
                                 "updated_at"])
    log(instance, "recalled", approver_id, {"node": node})
    _sync_data_table(instance)
    instance.refresh_from_db()
    return instance


def handle_user_deactivated(user_id: int) -> int:
    """Auto-skip every live slot held by ``user_id`` and re-advance.

    Was driven by the ``user.deactivated`` pub/sub event; in the monolith
    ``apps.users`` calls this through ``apps.approvals.interface``. Idempotent
    — a second run finds no live slots.
    """
    live = list(ApprovalAction.objects.filter(approver_id=user_id,
                                              acted_at__isnull=True))
    if not live:
        return 0
    now = timezone.now()
    ApprovalAction.objects.filter(id__in=[a.id for a in live]).update(
        action=ApprovalActionType.AUTO_SKIP, acted_at=now)

    touched = {a.request_id for a in live}
    for request_id in sorted(touched):
        instance = RequestInstance.objects.filter(pk=request_id).first()
        if instance is None or instance.status != RequestStatus.PENDING \
                or not instance.current_node_id:
            continue
        instance.requires_admin_attention = True
        instance.save(update_fields=["requires_admin_attention", "updated_at"])
        log(instance, "approver_deactivated", None, {"user_id": user_id})
        try:
            _advance(instance)
        except Exception as exc:  # noqa: BLE001
            # One broken workflow must not block the rest of the batch.
            log(instance, "advance_failed_after_deactivation", None,
                {"error": str(exc)})
    return len(touched)


def _sync_data_table(instance: RequestInstance) -> None:
    """Mirror the instance into its template's data table, if it has one."""
    from .template_data_table import sync_row_for_instance
    sync_row_for_instance(instance)
