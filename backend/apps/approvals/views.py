"""HTTP views — ``/api/requests/v1/*``.

Ported from ``services/requests/app/api/v1/*.py``. Views stay thin: parse,
authorize, map errors to status codes; the workflow logic lives in
``apps.approvals.services.*``.

**Error mapping.** The runtime raises three domain exceptions instead of
FastAPI's ``HTTPException``, so the mapping lives in one place here rather
than being re-raised at thirty call sites:

    Forbidden        -> 403
    RuntimeConflict  -> 409   (wrong state for this operation)
    RuntimeRejected  -> 422   (well-formed, but cannot be carried out)

``PermissionDenied`` and ``Http404`` are already handled by
``htqweb.http.api_view`` (403 / 404), so they pass straight through.

Method dispatchers and query-param helpers follow the same pattern as
``apps.tasks.views`` — see that module's docstring for the reasoning.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from functools import wraps

from django.db.models import Avg, Case, Count, DecimalField, F, Q, Sum, Value, When
from django.db.models.functions import Coalesce
from django.http import HttpResponse, StreamingHttpResponse
from django.utils import timezone
from pydantic import ValidationError

from htqweb.http import api_view, json_error

from . import schemas
from .services import dispatch, instance_service, permissions, sse
from .services import request_runtime as rr
from .services import template_data_table
from .services.request_runtime import Forbidden, RuntimeConflict, RuntimeRejected
from .services.template_validation import validate_template_version
from .util.slug import slugify


def _no_content() -> HttpResponse:
    return HttpResponse(status=204)


def _method_not_allowed(request):
    return json_error("Method Not Allowed", 405)


def _str_param(request, name: str, default=None):
    raw = request.GET.get(name)
    return raw if raw not in (None, "") else default


def _int_param(request, name: str):
    """``(value, error_response)`` -- error is a 422 JsonResponse when the
    param is present but not a valid integer; ``(None, None)`` when absent."""
    raw = request.GET.get(name)
    if raw in (None, ""):
        return None, None
    try:
        return int(raw), None
    except ValueError:
        return None, json_error(f"Invalid integer for '{name}': {raw!r}", 422)


def runtime_errors(fn):
    """Translate the runtime's domain exceptions into the original's codes."""

    @wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Forbidden as exc:
            return json_error(str(exc), 403)
        except RuntimeConflict as exc:
            return json_error(str(exc), 409)
        except RuntimeRejected as exc:
            return json_error(str(exc), 422)
    return wrapper


def _instance(instance) -> schemas.InstanceResponse:
    return schemas.InstanceResponse.model_validate(instance)


# ─────────────────────────────────────────────────────────────────────────
# Instances — /instances/
# ─────────────────────────────────────────────────────────────────────────

@api_view(methods=("GET",))
def _list_instances(request):
    return [_instance(row) for row in instance_service.list_for_user(
        request.token.user_id, box=_str_param(request, "box", "inbox"))]


@api_view(methods=("POST",), body=schemas.InstanceCreate, status=201)
@runtime_errors
def _create_instance(request, data: schemas.InstanceCreate):
    return _instance(instance_service.create_instance(data,
                                                      token=request.token))


def instances_collection(request):
    if request.method == "GET":
        return _list_instances(request)
    if request.method == "POST":
        return _create_instance(request)
    return _method_not_allowed(request)


@api_view(methods=("GET",))
def _get_instance(request, instance_id: int):
    return _instance(instance_service.get_or_404(instance_id))


@api_view(methods=("PATCH",), body=schemas.InstanceUpdate)
@runtime_errors
def _update_instance(request, instance_id: int, data: schemas.InstanceUpdate):
    return _instance(instance_service.update_draft(instance_id, data,
                                                   token=request.token))


def instance_detail(request, instance_id: int):
    if request.method == "GET":
        return _get_instance(request, instance_id=instance_id)
    if request.method == "PATCH":
        return _update_instance(request, instance_id=instance_id)
    return _method_not_allowed(request)


@api_view(methods=("POST",))
@runtime_errors
def submit_instance(request, instance_id: int):
    return _instance(instance_service.submit(instance_id, token=request.token))


@api_view(methods=("POST",))
@runtime_errors
def resubmit_instance(request, instance_id: int):
    return _instance(instance_service.submit(instance_id, token=request.token,
                                             resubmit=True))


# ─────────────────────────────────────────────────────────────────────────
# Approver actions — /instances/{id}/{approve,reject,...}/
# ─────────────────────────────────────────────────────────────────────────

def _act(request, instance_id: int, action: str, comment: str):
    instance = instance_service.get_or_404(instance_id)
    rr.act(instance, approver_id=request.token.user_id, action=action,
           comment=comment)
    instance.refresh_from_db()
    return _instance(instance)


@api_view(methods=("POST",), body=schemas.ActionRequest)
@runtime_errors
def approve(request, instance_id: int, data: schemas.ActionRequest):
    return _act(request, instance_id, "approve", data.comment)


@api_view(methods=("POST",), body=schemas.ActionRequest)
@runtime_errors
def reject(request, instance_id: int, data: schemas.ActionRequest):
    return _act(request, instance_id, "reject", data.comment)


@api_view(methods=("POST",), body=schemas.ActionRequest)
@runtime_errors
def request_changes(request, instance_id: int, data: schemas.ActionRequest):
    return _act(request, instance_id, "request_changes", data.comment)


@api_view(methods=("POST",), body=schemas.ActionRequest)
@runtime_errors
def cancel(request, instance_id: int, data: schemas.ActionRequest):
    instance = instance_service.get_or_404(instance_id)
    rr.cancel(instance, actor_id=request.token.user_id,
              is_elevated=request.token.is_elevated)
    instance.refresh_from_db()
    return _instance(instance)


@api_view(methods=("POST",), body=schemas.ActionRequest)
@runtime_errors
def recall(request, instance_id: int, data: schemas.ActionRequest):
    instance = instance_service.get_or_404(instance_id)
    rr.recall(instance, approver_id=request.token.user_id)
    instance.refresh_from_db()
    return _instance(instance)


@api_view(methods=("POST",), body=schemas.BatchActionRequest)
def batch_approve(request, data: schemas.BatchActionRequest):
    """Approve many requests in one call.

    Per-item error handling, not all-or-nothing: the original returns a
    result row per id so the UI can show which ones went through. Each item
    is attempted independently and its failure reported, never raised.
    """
    from .models import RequestInstance
    from .services.template_settings import settings_for_instance

    results = []
    for instance_id in data.ids:
        instance = RequestInstance.objects.filter(pk=instance_id).first()
        if instance is None:
            results.append({"id": instance_id, "ok": False,
                            "error": "not found"})
            continue
        if not settings_for_instance(instance)["allow_batch"]:
            results.append({"id": instance_id, "ok": False,
                            "error": "batch disabled"})
            continue
        try:
            rr.act(instance, approver_id=request.token.user_id,
                   action="approve", comment=data.comment)
            results.append({"id": instance_id, "ok": True})
        except (Forbidden, RuntimeConflict, RuntimeRejected) as exc:
            results.append({"id": instance_id, "ok": False,
                            "error": str(exc)})
    return {"results": results}


# ─────────────────────────────────────────────────────────────────────────
# Projects — /projects/
# ─────────────────────────────────────────────────────────────────────────

@api_view(methods=("GET",))
def _list_projects(request):
    from .models import RequestProject
    return [schemas.ProjectResponse.model_validate(row)
            for row in RequestProject.objects.order_by("-created_at")]


@api_view(methods=("POST",), body=schemas.ProjectCreate, admin=True, status=201)
def _create_project(request, data: schemas.ProjectCreate):
    from .models import RequestProject
    payload = data.model_dump()
    if payload.get("owner_id") is None:
        payload["owner_id"] = request.token.user_id
    # The original also called ensure_user_replica() here to avoid a FK
    # violation against request_users. With the replica gone (Р2) owner_id is
    # a plain int and there is no FK to violate — the self-heal is obsolete.
    return schemas.ProjectResponse.model_validate(
        RequestProject.objects.create(**payload))


def projects_collection(request):
    if request.method == "GET":
        return _list_projects(request)
    if request.method == "POST":
        return _create_project(request)
    return _method_not_allowed(request)


def _project_or_404(project_id: int):
    from django.http import Http404

    from .models import RequestProject
    project = RequestProject.objects.filter(pk=project_id).first()
    if project is None:
        raise Http404("Project not found")
    return project


@api_view(methods=("GET",))
def _get_project(request, project_id: int):
    return schemas.ProjectResponse.model_validate(_project_or_404(project_id))


@api_view(methods=("PATCH",), body=schemas.ProjectUpdate)
def _update_project(request, project_id: int, data: schemas.ProjectUpdate):
    project = _project_or_404(project_id)
    permissions.ensure_can_manage_project(project_id, request.token)
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(project, field, value)
    project.save()
    return schemas.ProjectResponse.model_validate(project)


@api_view(methods=("DELETE",), admin=True, status=204)
def _delete_project(request, project_id: int):
    _project_or_404(project_id).delete()
    return _no_content()


def project_detail(request, project_id: int):
    if request.method == "GET":
        return _get_project(request, project_id=project_id)
    if request.method == "PATCH":
        return _update_project(request, project_id=project_id)
    if request.method == "DELETE":
        return _delete_project(request, project_id=project_id)
    return _method_not_allowed(request)


@api_view(methods=("GET",))
def _list_members(request, project_id: int):
    from .models import RequestProjectMember
    return [schemas.MemberResponse.model_validate(row)
            for row in RequestProjectMember.objects
            .filter(project_id=project_id).order_by("user_id")]


@api_view(methods=("POST",), body=schemas.MemberAdd, status=201)
def _add_member(request, project_id: int, data: schemas.MemberAdd):
    from .models import RequestProjectMember
    _project_or_404(project_id)
    permissions.ensure_can_manage_project(project_id, request.token)
    member, _ = RequestProjectMember.objects.update_or_create(
        project_id=project_id, user_id=data.user_id,
        defaults={"role": data.role, "granted_by": request.token.user_id},
    )
    return schemas.MemberResponse.model_validate(member)


def project_members(request, project_id: int):
    if request.method == "GET":
        return _list_members(request, project_id=project_id)
    if request.method == "POST":
        return _add_member(request, project_id=project_id)
    return _method_not_allowed(request)


# ─────────────────────────────────────────────────────────────────────────
# Form templates — /templates/ (the form builder)
# ─────────────────────────────────────────────────────────────────────────
#
# Ported from ``services/requests/app/api/v1/forms.py``. Reads (list/get/
# get-version/preview) require only authentication; writes (create/update/
# publish/deactivate/activate/delete) go through
# ``permissions.ensure_can_manage_template`` -- a global admin, or an admin
# of the template's own project (never a project admin for a GLOBAL
# template, see that helper's docstring).

def _validated_or_422(schema_json: dict, workflow_json: dict):
    """``(schema, graph, None)`` on success, ``(None, None, error)`` on a
    422 -- both blobs plus their cross-references (condition nodes may only
    reference fields the form schema actually defines)."""
    try:
        schema, graph = validate_template_version(schema_json, workflow_json)
        return schema, graph, None
    except (ValidationError, ValueError) as exc:
        return None, None, json_error(f"Invalid template version: {exc}", 422)


def _template_or_404(template_id: int):
    from django.http import Http404

    from .models import RequestFormTemplate
    tpl = RequestFormTemplate.objects.filter(pk=template_id).first()
    if tpl is None:
        raise Http404("Template not found")
    return tpl


@api_view(methods=("GET",))
def _list_templates(request):
    from .models import RequestFormTemplate, TemplateStatus
    project_id, err = _int_param(request, "project_id")
    if err is not None:
        return err
    qs = (RequestFormTemplate.objects.filter(project_id=project_id)
          .exclude(status=TemplateStatus.DELETED)
          .order_by("-created_at"))
    return [schemas.TemplateResponse.model_validate(t) for t in qs]


@api_view(methods=("POST",), body=schemas.TemplateCreate, status=201)
def _create_template(request, data: schemas.TemplateCreate):
    from .models import RequestFormTemplate

    permissions.ensure_can_manage_template(data.project_id, request.token)
    slug = slugify(data.name)
    # Scoped by (project, slug) regardless of status -- mirrors the DB's own
    # UniqueConstraint, so a soft-deleted template still blocks its slug.
    if RequestFormTemplate.objects.filter(project_id=data.project_id, slug=slug).exists():
        return json_error(f"Template slug '{slug}' already exists in this scope", 409)
    tpl = RequestFormTemplate.objects.create(
        project_id=data.project_id, name=data.name, slug=slug,
        description=data.description, icon=data.icon, color=data.color,
        config_json=data.config_json, created_by=request.token.user_id,
    )
    template_data_table.ensure_source_for_template(tpl)
    return schemas.TemplateResponse.model_validate(tpl)


def templates_collection(request):
    if request.method == "GET":
        return _list_templates(request)
    if request.method == "POST":
        return _create_template(request)
    return _method_not_allowed(request)


@api_view(methods=("GET",))
def _get_template(request, template_id: int):
    return schemas.TemplateResponse.model_validate(_template_or_404(template_id))


@api_view(methods=("PATCH",), body=schemas.TemplateUpdate)
def _update_template(request, template_id: int, data: schemas.TemplateUpdate):
    tpl = _template_or_404(template_id)
    permissions.ensure_can_manage_template(tpl.project_id, request.token)
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(tpl, field, value)
    tpl.save()
    return schemas.TemplateResponse.model_validate(tpl)


@api_view(methods=("DELETE",), status=204)
def _delete_template(request, template_id: int):
    """Soft-delete: the template is hidden and the form is blocked, but its
    data table / reference data is kept. Owner + process admins retain
    access to it."""
    from .models import RequestReferenceSource, TemplateStatus

    tpl = _template_or_404(template_id)
    permissions.ensure_can_manage_template(tpl.project_id, request.token)

    # Preserve access to the (now-orphaned) data table for its owner + admins.
    src = RequestReferenceSource.objects.filter(template_id=tpl.id).first()
    if src is not None:
        keep = {int(x) for x in (src.access_ids or []) if isinstance(x, int)}
        if tpl.created_by:
            keep.add(int(tpl.created_by))
        for a in (tpl.config_json or {}).get("process_admin_ids") or []:
            if isinstance(a, int):
                keep.add(a)
        src.access_ids = sorted(keep)
        src.save(update_fields=["access_ids", "updated_at"])

    tpl.status = TemplateStatus.DELETED
    tpl.is_active = False
    tpl.save()
    return _no_content()


def template_detail(request, template_id: int):
    if request.method == "GET":
        return _get_template(request, template_id=template_id)
    if request.method == "PATCH":
        return _update_template(request, template_id=template_id)
    if request.method == "DELETE":
        return _delete_template(request, template_id=template_id)
    return _method_not_allowed(request)


@api_view(methods=("POST",))
def deactivate_template(request, template_id: int):
    from .models import TemplateStatus

    tpl = _template_or_404(template_id)
    permissions.ensure_can_manage_template(tpl.project_id, request.token)
    tpl.status = TemplateStatus.INACTIVE
    tpl.is_active = False
    tpl.save()
    return schemas.TemplateResponse.model_validate(tpl)


@api_view(methods=("POST",))
def activate_template(request, template_id: int):
    from django.http import Http404

    from .models import RequestFormTemplate, TemplateStatus
    tpl = RequestFormTemplate.objects.filter(pk=template_id).first()
    if tpl is None or tpl.status == TemplateStatus.DELETED:
        raise Http404("Template not found")
    permissions.ensure_can_manage_template(tpl.project_id, request.token)
    tpl.status = TemplateStatus.ACTIVE
    tpl.is_active = True
    tpl.save()
    return schemas.TemplateResponse.model_validate(tpl)


@api_view(methods=("POST",), body=schemas.VersionPublish, status=201)
def publish_version(request, template_id: int, data: schemas.VersionPublish):
    from django.db.models import Max

    from .models import RequestFormTemplateVersion

    tpl = _template_or_404(template_id)
    permissions.ensure_can_manage_template(tpl.project_id, request.token)
    _schema, _graph, err = _validated_or_422(data.schema_json, data.workflow_json)
    if err is not None:
        return err

    next_version = (RequestFormTemplateVersion.objects.filter(template=tpl)
                    .aggregate(Max("version"))["version__max"] or 0) + 1
    version = RequestFormTemplateVersion.objects.create(
        template=tpl, version=next_version,
        schema_json=data.schema_json, workflow_json=data.workflow_json,
        published_by=request.token.user_id,
    )
    tpl.current_version_id = version.id
    tpl.save(update_fields=["current_version_id", "updated_at"])
    template_data_table.sync_columns_for_template(tpl, data.schema_json)
    return schemas.VersionResponse.model_validate(version)


@api_view(methods=("GET",))
def get_version(request, template_id: int, version_id: int):
    from django.http import Http404

    from .models import RequestFormTemplateVersion
    version = RequestFormTemplateVersion.objects.filter(pk=version_id).first()
    if version is None or version.template_id != template_id:
        raise Http404("Version not found")
    return schemas.VersionResponse.model_validate(version)


@api_view(methods=("POST",), body=schemas.PreviewRequest)
def preview_template(request, data: schemas.PreviewRequest):
    schema, graph, err = _validated_or_422(data.schema_json, data.workflow_json)
    if err is not None:
        return err
    return schemas.PreviewResponse(valid=True, field_keys=sorted(schema.keys),
                                   node_count=len(graph.nodes))


# ─────────────────────────────────────────────────────────────────────────
# Statistics — /stats/*  (see the original's spec §6 for the five cuts)
# ─────────────────────────────────────────────────────────────────────────
#
# Ported from ``services/requests/app/api/v1/stats.py``. Read-only, any
# authenticated user (no admin gate in the original either). NOTE the two
# quirks carried over byte-for-byte from the source: ``overview`` and
# ``by-actor`` both compute a ``from``/``to`` default window but never
# actually apply it as a filter on the underlying query -- only ``heatmap``
# (which reads the daily rollup) filters by date. This looks like a latent
# bug in the original; per the porting brief it is kept AS-IS rather than
# "fixed", since the point of this port is behavioural parity.

_PROJECT_STATUSES = ("draft", "pending", "approved", "rejected", "cancelled", "returned")


def _default_from(days: int) -> dt.date:
    return timezone.now().date() - dt.timedelta(days=days)


def _date_param(request, name: str):
    """``(date_or_None, error_response)``."""
    raw = request.GET.get(name)
    if raw in (None, ""):
        return None, None
    try:
        return dt.date.fromisoformat(raw), None
    except ValueError:
        return None, json_error(f"Invalid date for '{name}': {raw!r}", 422)


@api_view(methods=("GET",))
def stats_overview(request):
    from .models import RequestInstance

    frm, err = _date_param(request, "from")
    if err is not None:
        return err
    to, err = _date_param(request, "to")
    if err is not None:
        return err
    frm = frm or _default_from(30)
    end = to or timezone.now().date()

    rows = (RequestInstance.objects.filter(submitted_at__isnull=False)
            .values("status")
            .annotate(count=Count("id"),
                     sum_amount=Coalesce(Sum("total_amount"), Decimal(0))))
    by_status = {s: {"count": 0, "sum_amount": 0} for s in _PROJECT_STATUSES}
    for row in rows:
        by_status[row["status"]] = {"count": int(row["count"]),
                                    "sum_amount": float(row["sum_amount"] or 0)}
    return {"from": frm.isoformat(), "to": end.isoformat(), "by_status": by_status}


@api_view(methods=("GET",))
def stats_by_project(request):
    from .models import RequestInstance, RequestProject, RequestStatus

    project_id, err = _int_param(request, "project_id")
    if err is not None:
        return err
    if project_id is None:
        return json_error("field required: project_id", 422)

    project = RequestProject.objects.filter(pk=project_id).first()
    if project is None:
        return {"project": None}

    agg = RequestInstance.objects.filter(project_id=project_id).aggregate(
        sum_approved=Coalesce(Sum(Case(
            When(status=RequestStatus.APPROVED, then=F("total_amount")),
            default=Value(0), output_field=DecimalField())), Decimal(0)),
        sum_pending=Coalesce(Sum(Case(
            When(status=RequestStatus.PENDING, then=F("total_amount")),
            default=Value(0), output_field=DecimalField())), Decimal(0)),
        count_approved=Coalesce(Sum(Case(
            When(status=RequestStatus.APPROVED, then=Value(1)), default=Value(0))), 0),
        count_pending=Coalesce(Sum(Case(
            When(status=RequestStatus.PENDING, then=Value(1)), default=Value(0))), 0),
    )
    sum_approved = float(agg["sum_approved"] or 0)
    budget = float(project.budget_limit) if project.budget_limit is not None else None
    return {
        "project": {"id": project.id, "name": project.name,
                    "budget_limit": budget, "currency": project.currency},
        "sum_approved": sum_approved,
        "sum_pending": float(agg["sum_pending"] or 0),
        "count_approved": int(agg["count_approved"] or 0),
        "count_pending": int(agg["count_pending"] or 0),
        "remaining": (budget - sum_approved) if budget is not None else None,
        "percent_used": (sum_approved / budget * 100) if budget and budget > 0 else None,
    }


@api_view(methods=("GET",))
def stats_by_template(request):
    from .models import RequestInstance

    frm, err = _date_param(request, "from")
    if err is not None:
        return err
    to, err = _date_param(request, "to")
    if err is not None:
        return err
    project_id, err = _int_param(request, "project_id")
    if err is not None:
        return err
    # ``frm``/``to`` are validated above (422 on malformed input, matching
    # the source's query-param typing) but -- per the module note -- the
    # source never actually applies them as a filter here either.

    cond = Q(submitted_at__isnull=False)
    if project_id is not None:
        cond &= Q(project_id=project_id)
    rows = (RequestInstance.objects.filter(cond)
            .values("template_id")
            .annotate(
                count=Count("id"),
                approved=Coalesce(Sum(Case(When(status="approved", then=Value(1)),
                                          default=Value(0))), 0),
                rejected=Coalesce(Sum(Case(When(status="rejected", then=Value(1)),
                                          default=Value(0))), 0),
                avg_amount=Coalesce(Avg(Case(When(status="approved", then=F("total_amount")))),
                                    Decimal(0)),
            ))
    return [
        {
            "template_id": int(row["template_id"]),
            "count": int(row["count"]),
            "approved": int(row["approved"]),
            "rejected": int(row["rejected"]),
            "avg_amount": float(row["avg_amount"] or 0),
            "approval_rate": (float(row["approved"]) / float(row["count"])
                              if row["count"] else 0.0),
        }
        for row in rows
    ]


@api_view(methods=("GET",))
def stats_by_actor(request):
    from .models import ApprovalAction, RequestInstance

    role = _str_param(request, "role", "initiator")
    if role not in ("initiator", "approver"):
        return json_error(f"Invalid role: {role!r}", 422)
    frm, err = _date_param(request, "from")
    if err is not None:
        return err
    to, err = _date_param(request, "to")
    if err is not None:
        return err
    limit, err = _int_param(request, "limit")
    if err is not None:
        return err
    limit = limit if limit is not None else 20
    # ``frm``/``to`` are validated above (422 on malformed input) but -- per
    # the module note -- the source never applies them as a filter here.

    if role == "initiator":
        rows = (RequestInstance.objects.filter(submitted_at__isnull=False)
                .values("initiator_id")
                .annotate(count=Count("id"),
                         approved=Coalesce(Sum(Case(
                             When(status="approved", then=Value(1)), default=Value(0))), 0))
                .order_by("-count")[:limit])
        id_field = "initiator_id"
    else:
        rows = (ApprovalAction.objects.filter(acted_at__isnull=False)
                .values("approver_id")
                .annotate(count=Count("id"),
                         approved=Coalesce(Sum(Case(
                             When(action="approve", then=Value(1)), default=Value(0))), 0))
                .order_by("-count")[:limit])
        id_field = "approver_id"

    return [
        {
            "user_id": int(row[id_field]),
            "count": int(row["count"]),
            "approved": int(row["approved"]),
            "approval_rate": (float(row["approved"]) / float(row["count"])
                              if row["count"] else 0.0),
        }
        for row in rows
    ]


@api_view(methods=("GET",))
def stats_heatmap(request):
    from .models import RequestStatsDaily

    frm, err = _date_param(request, "from")
    if err is not None:
        return err
    to, err = _date_param(request, "to")
    if err is not None:
        return err
    frm = frm or _default_from(30)
    end = to or timezone.now().date()

    rows = (RequestStatsDaily.objects.filter(date__range=(frm, end))
            .values("date")
            .annotate(created=Sum("created"), approved=Sum("approved"),
                     rejected=Sum("rejected"), cancelled=Sum("cancelled"))
            .order_by("date"))
    return [
        {
            "date": row["date"].isoformat(),
            "created": int(row["created"] or 0),
            "approved": int(row["approved"] or 0),
            "rejected": int(row["rejected"] or 0),
            "cancelled": int(row["cancelled"] or 0),
        }
        for row in rows
    ]


# ─────────────────────────────────────────────────────────────────────────
# SSE — /stream  (the ASGI surface of Поток B, PLAN.md §1.4 / §6.2)
# ─────────────────────────────────────────────────────────────────────────

async def stream(request):
    """Open a Server-Sent Events stream for the authenticated user.

    Deliberately NOT decorated with ``api_view``: that decorator is sync and
    reads credentials from the ``Authorization`` header only, while this
    endpoint must accept ``?token=`` because ``EventSource`` cannot set
    headers (see ``services/sse.py`` for the exposure this implies). Auth is
    therefore done explicitly here, against the same
    ``htqweb.authn.jwt.decode_token`` every other route uses — a separate
    transport, not a separate trust model.

    Service gating still applies: ``ServiceGateMiddleware`` matches on the
    URL prefix before resolution, so a disabled ``approvals`` answers 503
    here exactly as it does on every other route.

    Only ``GET`` — ``EventSource`` issues nothing else.
    """
    if request.method != "GET":
        return json_error("Method Not Allowed", 405)
    try:
        user_id = sse.authenticate(
            query_token=request.GET.get("token"),
            authorization=request.headers.get("Authorization"),
        )
    except sse.StreamAuthError as exc:
        return json_error(str(exc), 401)

    response = StreamingHttpResponse(
        sse.event_stream(dispatch.sse_channel(user_id)),
        content_type="text/event-stream",
    )
    response["Cache-Control"] = "no-cache"
    # Tells nginx not to buffer — without it the proxy holds frames until the
    # response ends, which for a stream is never.
    response["X-Accel-Buffering"] = "no"
    response["Connection"] = "keep-alive"
    return response


@api_view(methods=("DELETE",), status=204)
def remove_member(request, project_id: int, user_id: int):
    from django.http import Http404

    from .models import RequestProjectMember
    permissions.ensure_can_manage_project(project_id, request.token)
    deleted, _ = RequestProjectMember.objects.filter(
        project_id=project_id, user_id=user_id).delete()
    if not deleted:
        raise Http404("Member not found")
    return _no_content()


# ─────────────────────────────────────────────────────────────────────────
# Reference data sources -- /reference-sources/*  (Lark-Base-style lookup
# tables that ``reference`` form widgets read their options from)
# ─────────────────────────────────────────────────────────────────────────
#
# Ported from ``services/requests/app/api/v1/reference.py``. Management
# (create/update/delete a source, add/remove rows) is platform-admin only
# (``admin=True`` -- ``htqweb.authn.rbac.require_admin``, i.e. ``is_elevated``,
# the same predicate the original's own ``_require_admin`` checked); reading
# a source's metadata/rows and ``options`` needs only authentication.
#
# A template's auto-maintained data table (``template_id`` set) is the one
# exception: its rows, and the ``my-data-tables``/``access`` endpoints, are
# additionally gated through ``template_data_table.can_view_data_table`` /
# ``can_manage_data_table`` (owner, process admins, granted viewers, or a
# platform admin) -- see that module's docstring.

def _elevated(request) -> bool:
    return bool(request.token.is_elevated)


def _source_or_404(source_id: int):
    from django.http import Http404

    from .models import RequestReferenceSource
    src = RequestReferenceSource.objects.filter(pk=source_id).first()
    if src is None:
        raise Http404("Reference source not found")
    return src


def _source_dto(src) -> schemas.ReferenceSourceResponse:
    return schemas.ReferenceSourceResponse.model_validate(src)


@api_view(methods=("GET",))
def list_sources(request):
    from .models import RequestReferenceSource
    qs = RequestReferenceSource.objects.order_by("name")
    return [_source_dto(s) for s in qs]


@api_view(methods=("POST",), body=schemas.ReferenceSourceCreate, admin=True, status=201)
def create_source(request, data: schemas.ReferenceSourceCreate):
    from .models import RequestReferenceSource

    slug = data.slug or slugify(data.name)
    if RequestReferenceSource.objects.filter(slug=slug).exists():
        return json_error(f"slug '{slug}' already exists", 409)
    src = RequestReferenceSource.objects.create(
        slug=slug, name=data.name, columns_json=data.columns,
        created_by=request.token.user_id,
    )
    return _source_dto(src)


def sources_collection(request):
    if request.method == "GET":
        return list_sources(request)
    if request.method == "POST":
        return create_source(request)
    return _method_not_allowed(request)


def _data_table_dto(src, request) -> schemas.DataTableResponse:
    return schemas.DataTableResponse(
        id=src.id, slug=src.slug, name=src.name, columns=list(src.columns),
        template_id=src.template_id,
        access_ids=[int(x) for x in (src.access_ids or [])],
        can_manage=template_data_table.can_manage_data_table(
            src, request.token.user_id, _elevated(request)),
    )


@api_view(methods=("GET",))
def my_data_tables(request):
    """Template data tables the current user may see: created by them, a
    process admin of the template, explicitly granted access, or a platform
    admin."""
    from .models import RequestReferenceSource

    qs = (RequestReferenceSource.objects.filter(template_id__isnull=False)
          .order_by("name"))
    out = []
    for src in qs:
        if template_data_table.can_view_data_table(
                src, request.token.user_id, _elevated(request)):
            out.append(_data_table_dto(src, request))
    return out


@api_view(methods=("PATCH",), body=schemas.AccessUpdate)
def set_data_table_access(request, source_id: int, data: schemas.AccessUpdate):
    src = _source_or_404(source_id)
    if src.template_id is None:
        return json_error("not a template data table", 400)
    if not template_data_table.can_manage_data_table(
            src, request.token.user_id, _elevated(request)):
        return json_error("only the table owner can manage access", 403)
    src.access_ids = [int(x) for x in data.viewer_ids]
    src.save(update_fields=["access_ids", "updated_at"])
    return _data_table_dto(src, request)


@api_view(methods=("GET",))
def get_source(request, source_id: int):
    return _source_dto(_source_or_404(source_id))


@api_view(methods=("PATCH",), body=schemas.ReferenceSourceUpdate, admin=True)
def update_source(request, source_id: int, data: schemas.ReferenceSourceUpdate):
    src = _source_or_404(source_id)
    if data.name is not None:
        src.name = data.name
    if data.columns is not None:
        src.columns_json = data.columns
    src.save()
    return _source_dto(src)


@api_view(methods=("DELETE",), admin=True, status=204)
def delete_source(request, source_id: int):
    _source_or_404(source_id).delete()
    return _no_content()


def source_detail(request, source_id: int):
    if request.method == "GET":
        return get_source(request, source_id=source_id)
    if request.method == "PATCH":
        return update_source(request, source_id=source_id)
    if request.method == "DELETE":
        return delete_source(request, source_id=source_id)
    return _method_not_allowed(request)


@api_view(methods=("GET",))
def list_rows(request, source_id: int):
    from .models import RequestReferenceRow

    src = _source_or_404(source_id)
    if (src.template_id is not None
            and not template_data_table.can_view_data_table(
                src, request.token.user_id, _elevated(request))):
        return json_error("no access to this data table", 403)
    qs = RequestReferenceRow.objects.filter(source_id=source_id).order_by("id")
    return [schemas.ReferenceRowResponse.model_validate(r) for r in qs]


@api_view(methods=("POST",), body=schemas.ReferenceRowCreate, admin=True, status=201)
def add_row(request, source_id: int, data: schemas.ReferenceRowCreate):
    from .models import RequestReferenceRow

    _source_or_404(source_id)
    row = RequestReferenceRow.objects.create(source_id=source_id, data_json=data.data)
    return schemas.ReferenceRowResponse.model_validate(row)


def rows_collection(request, source_id: int):
    if request.method == "GET":
        return list_rows(request, source_id=source_id)
    if request.method == "POST":
        return add_row(request, source_id=source_id)
    return _method_not_allowed(request)


@api_view(methods=("DELETE",), admin=True, status=204)
def delete_row(request, source_id: int, row_id: int):
    from django.http import Http404

    from .models import RequestReferenceRow

    row = RequestReferenceRow.objects.filter(pk=row_id).first()
    if row is None or row.source_id != source_id:
        raise Http404("Row not found")
    row.delete()
    return _no_content()


@api_view(methods=("GET",))
def reference_options(request, slug: str):
    """Distinct values of ``column`` from the named source, optionally
    filtered where ``filter_col`` == ``filter_val`` (drives dependent
    selects)."""
    from .models import RequestReferenceRow, RequestReferenceSource

    column = _str_param(request, "column")
    if not column:
        return json_error("field required: column", 422)
    filter_col = _str_param(request, "filter_col")
    filter_val = _str_param(request, "filter_val")

    src = RequestReferenceSource.objects.filter(slug=slug).first()
    if src is None:
        return json_error("Reference source not found", 404)
    rows = RequestReferenceRow.objects.filter(source_id=src.id)
    seen: list[str] = []
    for row in rows:
        d = row.data_json or {}
        if filter_col and str(d.get(filter_col, "")) != str(filter_val):
            continue
        val = d.get(column)
        if val is None:
            continue
        s = str(val)
        if s not in seen:
            seen.append(s)
    return {"slug": slug, "column": column, "options": seen}
