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

from functools import wraps

from django.http import HttpResponse, StreamingHttpResponse

from htqweb.http import api_view, json_error

from . import schemas
from .services import dispatch, instance_service, permissions, sse
from .services import request_runtime as rr
from .services.request_runtime import Forbidden, RuntimeConflict, RuntimeRejected


def _no_content() -> HttpResponse:
    return HttpResponse(status=204)


def _method_not_allowed(request):
    return json_error("Method Not Allowed", 405)


def _str_param(request, name: str, default=None):
    raw = request.GET.get(name)
    return raw if raw not in (None, "") else default


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
