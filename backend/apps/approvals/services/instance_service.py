"""Instance CRUD around the workflow runtime.

Ported from ``services/requests/app/api/v1/instances.py`` and the query half
of ``InstanceRepository``. The lifecycle transitions themselves
(submit/act/cancel/recall) live in ``request_runtime`` — this module only
covers creating, listing, reading and editing a draft.
"""

from __future__ import annotations

from datetime import timedelta

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import Http404
from django.utils import timezone

from ..models import (
    ApprovalAction, RequestFormTemplate, RequestInstance, RequestStatus,
    RequestWatcher,
)
from . import request_runtime
from .request_runtime import RuntimeConflict
from .template_settings import settings_for_instance, settings_for_template


def get_or_404(instance_id: int) -> RequestInstance:
    instance = RequestInstance.objects.filter(pk=instance_id).first()
    if instance is None:
        raise Http404("Request not found")
    return instance


def list_for_user(user_id: int, *, box: str = "inbox") -> list[RequestInstance]:
    """The four Lark-parity mailboxes.

    * ``sent``  — requests the user initiated (Отправленные)
    * ``cc``    — requests the user follows as a watcher (Копия)
    * ``done``  — requests the user has already acted on (Готово)
    * ``inbox`` — pending requests awaiting the user's action (Список дел)

    Any unknown value falls through to ``inbox``, matching the original's
    ``else`` branch rather than erroring — the box name comes from a UI tab.
    """
    qs = RequestInstance.objects.all()
    if box == "sent":
        qs = qs.filter(initiator_id=user_id)
    elif box == "cc":
        qs = qs.filter(pk__in=RequestWatcher.objects.filter(user_id=user_id)
                       .values("request_id"))
    elif box == "done":
        qs = qs.filter(pk__in=ApprovalAction.objects
                       .filter(approver_id=user_id, acted_at__isnull=False)
                       .values("request_id"))
    else:
        qs = qs.filter(pk__in=ApprovalAction.objects
                       .filter(approver_id=user_id, acted_at__isnull=True)
                       .values("request_id"))
    return list(qs.order_by("-created_at"))


@transaction.atomic
def create_instance(data, *, token) -> RequestInstance:
    template = RequestFormTemplate.objects.filter(pk=data.template_id).first()
    if template is None:
        raise Http404("Template not found")
    if template.status != "active":
        raise RuntimeConflict("Форма заблокирована")
    if template.current_version_id is None:
        raise RuntimeConflict("template has no published version")

    initiator_id = token.user_id
    delegated = (data.on_behalf_of is not None
                 and data.on_behalf_of != token.user_id)
    if delegated:
        settings = settings_for_template(template.id)
        # Both conditions, as in the original: the template must opt in AND
        # the actor must be elevated. Either alone is not enough.
        if not settings["allow_delegate_submission"] or not token.is_elevated:
            raise PermissionDenied("delegated submission is not allowed")
        initiator_id = data.on_behalf_of

    instance = RequestInstance.objects.create(
        code=request_runtime.next_code(template),
        template=template,
        template_version_id=template.current_version_id,
        project_id=(data.project_id if data.project_id is not None
                    else template.project_id),
        initiator_id=initiator_id,
        title=data.title,
        form_values_json=data.form_values,
        status=RequestStatus.DRAFT,
    )
    if delegated:
        request_runtime.log(instance, "created_on_behalf", token.user_id,
                            {"for": initiator_id})
    else:
        request_runtime.log(instance, "created", token.user_id, None)

    from .template_data_table import sync_row_for_instance
    sync_row_for_instance(instance)
    instance.refresh_from_db()
    return instance


@transaction.atomic
def update_draft(instance_id: int, data, *, token) -> RequestInstance:
    """Edit a draft, a returned request, or — if the template allows it — a
    recently approved one."""
    instance = get_or_404(instance_id)
    if instance.initiator_id != token.user_id:
        raise PermissionDenied("only the initiator can edit")

    editable = instance.status in (RequestStatus.DRAFT, RequestStatus.RETURNED)
    if not editable and instance.status == RequestStatus.APPROVED:
        settings = settings_for_instance(instance)
        within = (
            instance.finalized_at is not None
            and (timezone.now() - instance.finalized_at)
            <= timedelta(days=int(settings["modify_within_days"] or 0))
        )
        editable = bool(settings["allow_modify_approved"]) and within
    if not editable:
        raise RuntimeConflict("request is not editable in its current state")

    if data.title is not None:
        instance.title = data.title
    if data.form_values is not None:
        instance.form_values_json = data.form_values
    instance.save()

    from .template_data_table import sync_row_for_instance
    sync_row_for_instance(instance)
    instance.refresh_from_db()
    return instance


def submit(instance_id: int, *, token, resubmit: bool = False) -> RequestInstance:
    instance = get_or_404(instance_id)
    verb = "resubmit" if resubmit else "submit"
    if instance.initiator_id != token.user_id:
        raise PermissionDenied(f"only the initiator can {verb}")
    if resubmit and instance.status != RequestStatus.RETURNED:
        raise RuntimeConflict("only a returned request can be resubmitted")
    request_runtime.submit(instance, actor_id=token.user_id)
    instance.refresh_from_db()
    return instance
