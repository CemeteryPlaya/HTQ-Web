"""HTTP views — ``/api/tasks/v1/*``.

Ported from ``services/task/app/api/v1/*.py``. Views stay thin (parse, auth,
status code); domain logic lives in ``apps.tasks.services.*``.

Two mechanics recur throughout and are worth reading once:

* **Method dispatchers.** ``htqweb.http.api_view`` binds one method set and
  one body schema per decorated function, but most of these URLs serve
  several methods with different bodies (``GET``/``POST`` on a collection,
  ``PATCH``/``DELETE`` on a detail). Each shared URL therefore gets a small
  plain dispatcher that routes on ``request.method`` and falls back to a 405
  envelope — the same 405 a router gives for an unregistered method.
* **Query parsing.** FastAPI validated query params from type hints; there
  is no equivalent here, so ``_int_param``/``_bool_param`` do it explicitly
  and return the original's 422 envelope on a malformed value rather than
  letting an ``int()`` blow up into a 500.
"""

from __future__ import annotations

from datetime import date, timedelta

from django.http import HttpResponse

from htqweb.http import api_view, json_error

from . import schemas
from .services import calendar_service
from .services import gantt_service
from .services import link_service
from .services import notification_service
from .services import project_service
from .services import reference_service as ref_svc
from .services import sequence_service
from .services import task_content_service
from .services import task_response
from .services import task_service


def _no_content() -> HttpResponse:
    """204 with an empty body. ``api_view``'s ``status=`` only applies to
    serialised return values, so a bare 204 needs a real response object."""
    return HttpResponse(status=204)


# ── query-parameter helpers ─────────────────────────────────────────────

def _param_error(name: str, message: str):
    """422 in the shape pydantic/FastAPI produced for a bad query param."""
    return json_error(
        [{"type": "value_error", "loc": ["query", name], "msg": message}], 422
    )


def _int_param(request, name: str, default=None, *, minimum=None, maximum=None):
    raw = request.GET.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise _ParamError(_param_error(name, "Input should be a valid integer"))
    if minimum is not None and value < minimum:
        raise _ParamError(
            _param_error(name, f"Input should be greater than or equal to {minimum}")
        )
    if maximum is not None and value > maximum:
        raise _ParamError(
            _param_error(name, f"Input should be less than or equal to {maximum}")
        )
    return value


def _bool_param(request, name: str, default: bool) -> bool:
    raw = request.GET.get(name)
    if raw is None or raw == "":
        return default
    return raw.lower() in ("1", "true", "yes", "on")


def _str_param(request, name: str, default=None):
    raw = request.GET.get(name)
    return raw if raw not in (None, "") else default


def _date_param(request, name: str, *, required: bool = False):
    raw = request.GET.get(name)
    if raw in (None, ""):
        if required:
            raise _ParamError(
                json_error([{"type": "missing", "loc": ["query", name],
                             "msg": "Field required"}], 422))
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        raise _ParamError(
            _param_error(name, "Input should be a valid date in YYYY-MM-DD format")
        )


class _ParamError(Exception):
    """Carries a ready-made error response out of a query-param helper.

    A sentinel exception rather than a returned error object: the helpers are
    called inline inside argument lists, where checking each result would
    bury the actual logic.
    """

    def __init__(self, response):
        self.response = response


def _method_not_allowed(request):
    return json_error("Method Not Allowed", 405)


# ─────────────────────────────────────────────────────────────────────────
# Labels — /labels/ , /labels/{id}/
# ─────────────────────────────────────────────────────────────────────────

@api_view(methods=("GET",))
def _list_labels(request):
    return [schemas.LabelResponse.model_validate(row)
            for row in ref_svc.list_labels()]


@api_view(methods=("POST",), body=schemas.LabelCreate, status=201)
def _create_label(request, data: schemas.LabelCreate):
    return schemas.LabelResponse.model_validate(
        ref_svc.create_label(name=data.name, color=data.color)
    )


def labels_collection(request):
    if request.method == "GET":
        return _list_labels(request)
    if request.method == "POST":
        return _create_label(request)
    return _method_not_allowed(request)


@api_view(methods=("PATCH",), body=schemas.LabelUpdate)
def _update_label(request, label_id: int, data: schemas.LabelUpdate):
    return schemas.LabelResponse.model_validate(
        ref_svc.update_label(label_id, data.model_dump(exclude_unset=True))
    )


@api_view(methods=("DELETE",), status=204)
def _delete_label(request, label_id: int):
    ref_svc.delete_label(label_id)
    return _no_content()


def label_detail(request, label_id: int):
    if request.method == "PATCH":
        return _update_label(request, label_id=label_id)
    if request.method == "DELETE":
        return _delete_label(request, label_id=label_id)
    return _method_not_allowed(request)


# ─────────────────────────────────────────────────────────────────────────
# Task types — /task-types/ , /task-types/{id}/
# ─────────────────────────────────────────────────────────────────────────

@api_view(methods=("GET",))
def _list_task_types(request):
    return [schemas.TaskTypeResponse.model_validate(row)
            for row in ref_svc.list_task_types()]


@api_view(methods=("POST",), body=schemas.TaskTypeCreate, status=201)
def _create_task_type(request, data: schemas.TaskTypeCreate):
    try:
        row = ref_svc.create_task_type(slug=data.slug, name=data.name,
                                       color=data.color, icon=data.icon)
    except ValueError as exc:
        # The original answers 409 for a slug that is already taken.
        return json_error(str(exc), 409)
    return schemas.TaskTypeResponse.model_validate(row)


def task_types_collection(request):
    if request.method == "GET":
        return _list_task_types(request)
    if request.method == "POST":
        return _create_task_type(request)
    return _method_not_allowed(request)


@api_view(methods=("PATCH",), body=schemas.TaskTypeUpdate)
def _update_task_type(request, type_id: int, data: schemas.TaskTypeUpdate):
    return schemas.TaskTypeResponse.model_validate(
        ref_svc.update_task_type(type_id, data.model_dump(exclude_unset=True))
    )


@api_view(methods=("DELETE",), status=204)
def _delete_task_type(request, type_id: int):
    # ``PermissionDenied`` for a system row -> api_view renders the 403 the
    # original raised explicitly.
    ref_svc.delete_task_type(type_id)
    return _no_content()


def task_type_detail(request, type_id: int):
    if request.method == "PATCH":
        return _update_task_type(request, type_id=type_id)
    if request.method == "DELETE":
        return _delete_task_type(request, type_id=type_id)
    return _method_not_allowed(request)


# ─────────────────────────────────────────────────────────────────────────
# Equipment — /equipment/ , /equipment/{id}
# ─────────────────────────────────────────────────────────────────────────

@api_view(methods=("GET",))
def _list_equipment(request):
    try:
        active_only = _bool_param(request, "active_only", True)
    except _ParamError as exc:
        return exc.response
    return [schemas.EquipmentResponse.model_validate(row)
            for row in ref_svc.list_equipment(active_only)]


@api_view(methods=("POST",), body=schemas.EquipmentCreate, status=201)
def _create_equipment(request, data: schemas.EquipmentCreate):
    return schemas.EquipmentResponse.model_validate(
        ref_svc.create_equipment(**data.model_dump())
    )


def equipment_collection(request):
    if request.method == "GET":
        return _list_equipment(request)
    if request.method == "POST":
        return _create_equipment(request)
    return _method_not_allowed(request)


@api_view(methods=("PATCH",), body=schemas.EquipmentUpdate)
def _update_equipment(request, equipment_id: int, data: schemas.EquipmentUpdate):
    return schemas.EquipmentResponse.model_validate(
        ref_svc.update_equipment(equipment_id,
                                 data.model_dump(exclude_unset=True))
    )


@api_view(methods=("DELETE",), status=204)
def _delete_equipment(request, equipment_id: int):
    ref_svc.delete_equipment(equipment_id)
    return _no_content()


def equipment_detail(request, equipment_id: int):
    if request.method == "PATCH":
        return _update_equipment(request, equipment_id=equipment_id)
    if request.method == "DELETE":
        return _delete_equipment(request, equipment_id=equipment_id)
    return _method_not_allowed(request)


# ─────────────────────────────────────────────────────────────────────────
# Sequences — /sequences/{prefix}/next  (admin-only)
# ─────────────────────────────────────────────────────────────────────────

@api_view(methods=("POST",), admin=True)
def next_task_key(request, project_prefix: str):
    """Hand out the next task key for a prefix.

    The FastAPI original was dead on arrival: its ``next_task_key`` helper
    addressed ``TaskSequence.prefix``/``.last_number``, columns the model
    never had (they are ``name``/``current_value``), so every call raised.
    Ported against the real columns — the endpoint's contract
    (``{"key": "TASK-17"}``, admin-only) is what the route always declared.
    """
    return {"key": sequence_service.next_task_key(project_prefix)}


# ─────────────────────────────────────────────────────────────────────────
# Tasks — /tasks/ , /tasks/stats/ , /tasks/{id}/ and its sub-resources
#
# Permission model (services/task/app/api/v1/tasks.py):
#   full edit (any field)                 — elevated / reporter / supervisor
#                                           / delegate
#   soft edit (status, progress, comment) — + any assignee
#   read                                  — visibility filter in the service
# ─────────────────────────────────────────────────────────────────────────

@api_view(methods=("GET",))
def _list_tasks(request):
    try:
        offset = _int_param(request, "offset", 0, minimum=0)
        limit = _int_param(request, "limit", 50, minimum=1, maximum=200)
        filters = {
            "status": _str_param(request, "status"),
            "priority": _str_param(request, "priority"),
            "task_type": _str_param(request, "task_type"),
            "task_type_id": _int_param(request, "task_type_id"),
            "assignee_id": _int_param(request, "assignee_id"),
            "reporter_id": _int_param(request, "reporter_id"),
            "supervisor_id": _int_param(request, "supervisor_id"),
            "department_id": _int_param(request, "department_id"),
            "project_id": _int_param(request, "project_id"),
            "project_unset": _bool_param(request, "standalone", False),
            "parent_id": _int_param(request, "parent_id"),
            "label_id": _int_param(request, "label_id"),
            "search": _str_param(request, "search"),
        }
    except _ParamError as exc:
        return exc.response

    visibility, department_id = task_service.scope_for(request.token)
    tasks = task_service.list_tasks(
        offset=offset, limit=limit, visibility=visibility,
        visibility_user_id=request.token.user_id,
        visibility_department_id=department_id, **filters,
    )
    return task_response.build_list(tasks)


@api_view(methods=("POST",), body=schemas.TaskCreate, status=201)
def _create_task(request, data: schemas.TaskCreate):
    task = task_service.create_task(data, user_id=request.token.user_id)
    # Re-read through the visibility-aware loader so the response is built
    # from the same fully-prefetched shape every other endpoint returns.
    return task_response.build_detail(task_service.get_task(task.id))


def tasks_collection(request):
    if request.method == "GET":
        return _list_tasks(request)
    if request.method == "POST":
        return _create_task(request)
    return _method_not_allowed(request)


@api_view(methods=("GET",))
def task_stats(request):
    try:
        department_id = _int_param(request, "department_id")
        project_id = _int_param(request, "project_id")
    except _ParamError as exc:
        return exc.response
    visibility, visibility_department_id = task_service.scope_for(
        request.token, reports=True
    )
    return schemas.TaskStats.model_validate(task_service.task_stats(
        department_id=department_id, project_id=project_id,
        visibility=visibility, visibility_user_id=request.token.user_id,
        visibility_department_id=visibility_department_id,
    ))


@api_view(methods=("GET",))
def _get_task(request, task_id: int):
    return task_response.build_detail(
        task_service.load_for_action(task_id, request.token)
    )


@api_view(methods=("PATCH",), body=schemas.TaskUpdate)
def _update_task(request, task_id: int, data: schemas.TaskUpdate):
    task = task_service.load_for_action(task_id, request.token)
    # Status/progress alone need only the soft-edit role; touching anything
    # else requires full edit.
    fields = set(data.model_dump(exclude_unset=True))
    if fields and fields.issubset({"status", "progress_percent"}):
        task_service.require_soft_edit(task, request.token)
    else:
        task_service.require_full_edit(task, request.token)

    try:
        task_service.update_task(task_id, data, user_id=request.token.user_id)
    except ValueError as exc:
        # Rejected FSM transition — 400, as in the original.
        return json_error(str(exc), 400)
    return task_response.build_detail(task_service.get_task(task_id))


@api_view(methods=("DELETE",), status=204)
def _delete_task(request, task_id: int):
    task = task_service.load_for_action(task_id, request.token)
    task_service.require_full_edit(task, request.token)
    task_service.delete_task(task_id)
    return _no_content()


def task_detail(request, task_id: int):
    if request.method == "GET":
        return _get_task(request, task_id=task_id)
    if request.method == "PATCH":
        return _update_task(request, task_id=task_id)
    if request.method == "DELETE":
        return _delete_task(request, task_id=task_id)
    return _method_not_allowed(request)


@api_view(methods=("GET",))
def task_transitions(request, task_id: int):
    return [{"status": status}
            for status in task_service.available_transitions(task_id)]


@api_view(methods=("PATCH",), body=schemas.AssigneesUpdate)
def update_assignees(request, task_id: int, data: schemas.AssigneesUpdate):
    task = task_service.load_for_action(task_id, request.token)
    task_service.require_full_edit(task, request.token)
    task_service.replace_assignees(task_id, data.assignees,
                                   actor_id=request.token.user_id)
    return task_response.build_detail(task_service.get_task(task_id))


@api_view(methods=("PATCH",), body=schemas.SupervisorUpdate)
def update_supervisor(request, task_id: int, data: schemas.SupervisorUpdate):
    task = task_service.load_for_action(task_id, request.token)
    task_service.require_full_edit(task, request.token)
    task_service.set_supervisor(task_id, data.user_id,
                                actor_id=request.token.user_id)
    return task_response.build_detail(task_service.get_task(task_id))


@api_view(methods=("POST",), body=schemas.DelegateCreate, status=201)
def _add_delegate(request, task_id: int, data: schemas.DelegateCreate):
    task = task_service.load_for_action(task_id, request.token)
    # Only the supervisor (or an admin) may delegate. Reporters and existing
    # delegates deliberately cannot — otherwise delegates self-propagate.
    if not request.token.is_elevated and task.supervisor_id != request.token.user_id:
        return json_error("Only the supervisor (or admin) can add delegates", 403)
    task_service.add_delegate(task_id, data.user_id,
                              granted_by=request.token.user_id)
    return task_response.build_detail(task_service.get_task(task_id))


def task_delegates(request, task_id: int):
    if request.method == "POST":
        return _add_delegate(request, task_id=task_id)
    return _method_not_allowed(request)


@api_view(methods=("DELETE",))
def remove_delegate(request, task_id: int, user_id: int):
    """The supervisor can revoke anyone; a delegate may also give up their
    own seat. Returns the task (200), not 204 — as the original did."""
    task = task_service.load_for_action(task_id, request.token)
    is_self = user_id == request.token.user_id
    is_supervisor = task.supervisor_id == request.token.user_id
    if not (request.token.is_elevated or is_supervisor or is_self):
        return json_error("Cannot revoke another user's delegate seat", 403)
    task_service.remove_delegate(task_id, user_id,
                                 actor_id=request.token.user_id)
    return task_response.build_detail(task_service.get_task(task_id))


@api_view(methods=("POST",), status=201)
def _watch_task(request, task_id: int):
    task_service.load_for_action(task_id, request.token)
    task_service.add_watcher(task_id, request.token.user_id)
    return task_response.build_detail(task_service.get_task(task_id))


@api_view(methods=("DELETE",))
def _unwatch_task(request, task_id: int):
    task_service.load_for_action(task_id, request.token)
    task_service.remove_watcher(task_id, request.token.user_id)
    return task_response.build_detail(task_service.get_task(task_id))


def task_watch(request, task_id: int):
    """Self-only subscription — no user id in the path by design."""
    if request.method == "POST":
        return _watch_task(request, task_id=task_id)
    if request.method == "DELETE":
        return _unwatch_task(request, task_id=task_id)
    return _method_not_allowed(request)


@api_view(methods=("PATCH",), body=schemas.ProgressUpdate)
def update_progress(request, task_id: int, data: schemas.ProgressUpdate):
    task = task_service.load_for_action(task_id, request.token)
    task_service.require_soft_edit(task, request.token)
    task_service.set_progress(task_id, data.percent,
                              actor_id=request.token.user_id)
    return task_response.build_detail(task_service.get_task(task_id))


# ─────────────────────────────────────────────────────────────────────────
# Comments / attachments / activity on a task
# ─────────────────────────────────────────────────────────────────────────

@api_view(methods=("GET",))
def _list_comments(request, task_id: int):
    return task_content_service.list_comments(task_id)


@api_view(methods=("POST",), body=schemas.CommentCreate, status=201)
def _create_comment(request, task_id: int, data: schemas.CommentCreate):
    return task_content_service.create_comment(task_id, data.body,
                                               request.token.user_id)


def task_comments(request, task_id: int):
    if request.method == "GET":
        return _list_comments(request, task_id=task_id)
    if request.method == "POST":
        return _create_comment(request, task_id=task_id)
    return _method_not_allowed(request)


@api_view(methods=("GET",))
def _list_attachments(request, task_id: int):
    return task_content_service.list_attachments(task_id)


@api_view(methods=("POST",), status=201)
def _upload_attachment(request, task_id: int):
    """Store an uploaded file and record it against the task.

    Decision Р3: the bytes go through ``apps.media_files.interface.store_file``
    instead of the original's local ``uploads/task_attachments`` directory,
    so attachments get the platform's storage, scope policy and gating.

    ``task_attachment`` is a RESTRICTED scope, so ``store_file`` requires the
    caller to vouch for the write (``internal_authorized``). This domain does
    that only after its own soft-edit check passes — the vouch is the result
    of a permission decision, never a constant.
    """
    from apps.media_files import interface as media_interface

    task = task_service.load_for_action(task_id, request.token)
    task_service.require_soft_edit(task, request.token)

    upload = request.FILES.get("file")
    if upload is None:
        return json_error(
            [{"type": "missing", "loc": ["body", "file"],
              "msg": "Field required"}], 422)

    try:
        stored = media_interface.store_file(
            data=upload.read(),
            filename=upload.name or "unnamed",
            mime=upload.content_type or "application/octet-stream",
            scope="task_attachment",
            owner_id=request.token.user_id,
            internal_authorized=True,
        )
    except Exception as exc:
        # media documents ``UploadValidationError`` (oversize / wrong mime /
        # undecodable image) as part of store_file's contract, but the class
        # lives in ``apps.media_files.services.upload_service`` and the
        # isolation lint only permits importing a neighbour's ``interface``
        # — so it is matched by name. Everything else is a genuine fault:
        # re-raise and let api_view render its 500 envelope.
        #
        # Worth folding into media's interface as a re-export; that is the
        # owner's change to make, not this domain's (PLAN.md §1.5 п.3).
        if type(exc).__name__ != "UploadValidationError":
            raise
        return json_error(str(exc), 422)

    return task_content_service.create_attachment(
        task_id,
        # The storage key, not a local path — what media hands back is the
        # canonical reference for later reads.
        file_path=str(stored.get("url") or stored.get("id")),
        filename=upload.name or "unnamed",
        uploaded_by_id=request.token.user_id,
    )


def task_attachments(request, task_id: int):
    if request.method == "GET":
        return _list_attachments(request, task_id=task_id)
    if request.method == "POST":
        return _upload_attachment(request, task_id=task_id)
    return _method_not_allowed(request)


@api_view(methods=("GET",))
def task_activity(request, task_id: int):
    return task_content_service.list_activity(task_id)


# ─────────────────────────────────────────────────────────────────────────
# Task links — /task-links/
# ─────────────────────────────────────────────────────────────────────────

@api_view(methods=("POST",), body=schemas.LinkCreate, status=201)
def _create_link(request, data: schemas.LinkCreate):
    try:
        link = link_service.create_link(source_id=data.source_id,
                                        target_id=data.target_id,
                                        link_type=data.link_type,
                                        user_id=request.token.user_id)
    except ValueError as exc:
        return json_error(str(exc), 400)
    return schemas.LinkResponse.model_validate({
        "id": link.id, "source_id": link.source_id,
        "target_id": link.target_id, "link_type": link.link_type,
        "created_by_id": link.created_by_id,
        "source_key": link.source.key, "source_summary": link.source.summary,
        "target_key": link.target.key, "target_summary": link.target.summary,
        "created_at": str(link.created_at),
    })


def links_collection(request):
    if request.method == "POST":
        return _create_link(request)
    return _method_not_allowed(request)


@api_view(methods=("DELETE",), status=204)
def link_detail(request, link_id: int):
    link_service.delete_link(link_id)
    return _no_content()


# ─────────────────────────────────────────────────────────────────────────
# Projects — /projects/
# ─────────────────────────────────────────────────────────────────────────

@api_view(methods=("GET",))
def _list_projects(request):
    employee_scope, department_id = project_service.scope_for(request.token)
    return project_service.build_responses(project_service.list_projects(
        employee_scope=employee_scope, department_id=department_id))


@api_view(methods=("POST",), body=schemas.ProjectCreate, status=201)
def _create_project(request, data: schemas.ProjectCreate):
    return project_service.build_response(project_service.create_project(
        data.model_dump(), creator_id=request.token.user_id))


def projects_collection(request):
    if request.method == "GET":
        return _list_projects(request)
    if request.method == "POST":
        return _create_project(request)
    return _method_not_allowed(request)


@api_view(methods=("GET",))
def _get_project(request, project_id: int):
    employee_scope, department_id = project_service.scope_for(request.token)
    return project_service.build_response(project_service.get_project(
        project_id, employee_scope=employee_scope,
        department_id=department_id))


@api_view(methods=("PATCH",), body=schemas.ProjectUpdate)
def _update_project(request, project_id: int, data: schemas.ProjectUpdate):
    return project_service.build_response(project_service.update_project(
        project_id, data.model_dump(exclude_unset=True)))


@api_view(methods=("DELETE",), status=204)
def _delete_project(request, project_id: int):
    project_service.delete_project(project_id)
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
def project_tasks(request, project_id: int):
    """Flat task list for a project — the UI builds the tree itself."""
    employee_scope, department_id = project_service.scope_for(request.token)
    # 404s first if the project is out of scope, so this cannot be used to
    # enumerate tasks of a project the caller may not see.
    project_service.get_project(project_id, employee_scope=employee_scope,
                                department_id=department_id)
    tasks = task_service.list_tasks(
        limit=1000, project_id=project_id,
        department_id=department_id if employee_scope else None,
    )
    return task_response.build_list(tasks)


# ─────────────────────────────────────────────────────────────────────────
# Resource assignments — /assignments/
# ─────────────────────────────────────────────────────────────────────────

@api_view(methods=("GET",))
def _list_assignments(request):
    try:
        task_id = _int_param(request, "task_id")
    except _ParamError as exc:
        return exc.response
    if task_id is None:
        # ``task_id`` is a required query param in the original.
        return json_error([{"type": "missing", "loc": ["query", "task_id"],
                            "msg": "Field required"}], 422)
    return task_content_service.list_assignments(task_id)


@api_view(methods=("POST",), body=schemas.AssignmentCreate, status=201)
def _create_assignment(request, data: schemas.AssignmentCreate):
    try:
        return task_content_service.create_assignment(data)
    except ValueError as exc:
        return json_error(str(exc), 422)


def assignments_collection(request):
    if request.method == "GET":
        return _list_assignments(request)
    if request.method == "POST":
        return _create_assignment(request)
    return _method_not_allowed(request)


@api_view(methods=("DELETE",), status=204)
def assignment_detail(request, assignment_id: int):
    task_content_service.delete_assignment(assignment_id)
    return _no_content()


# ─────────────────────────────────────────────────────────────────────────
# Notifications — /notifications/
#
# Every route is caller-scoped; there is no path or body parameter that
# names a recipient, so one user can never read or mutate another's feed.
# ─────────────────────────────────────────────────────────────────────────

@api_view(methods=("GET",))
def notifications_collection(request):
    try:
        limit = _int_param(request, "limit", 50, minimum=1, maximum=200)
    except _ParamError as exc:
        return exc.response
    return notification_service.latest(request.token.user_id, limit)


@api_view(methods=("GET",))
def notification_history(request):
    try:
        page = _int_param(request, "page", 1, minimum=1)
        limit = _int_param(request, "limit", 25, minimum=1, maximum=100)
    except _ParamError as exc:
        return exc.response
    status = _str_param(request, "status", "all")
    if status not in ("all", "unread", "read"):
        return _param_error("status",
                            "Input should be 'all', 'unread' or 'read'")
    return notification_service.history(
        request.token.user_id, page=page, limit=limit, status=status,
        target_type=_str_param(request, "target_type"),
    )


@api_view(methods=("POST",), status=204)
def notification_mark_read(request, notification_id: int):
    notification_service.mark_read(notification_id, request.token.user_id)
    return _no_content()


@api_view(methods=("POST",), status=204)
def notification_mark_unread(request, notification_id: int):
    notification_service.mark_unread(notification_id, request.token.user_id)
    return _no_content()


@api_view(methods=("POST",), status=204)
def notifications_mark_all_read(request):
    notification_service.mark_all_read(request.token.user_id)
    return _no_content()


@api_view(methods=("DELETE",), status=204)
def notification_detail(request, notification_id: int):
    notification_service.delete(notification_id, request.token.user_id)
    return _no_content()


# ─────────────────────────────────────────────────────────────────────────
# Gantt reports — /reports/gantt , /reports/resource-gantt
# ─────────────────────────────────────────────────────────────────────────

def _csv_ints(value: str | None) -> list[int] | None:
    if not value:
        return None
    return [int(x) for x in value.split(",") if x.strip().isdigit()]


def _csv(value: str | None) -> list[str] | None:
    if not value:
        return None
    return [x.strip() for x in value.split(",") if x.strip()]


@api_view(methods=("GET",))
def reports_gantt(request):
    return schemas.ReportsGanttResponse.model_validate(
        gantt_service.reports_gantt(_csv_ints(_str_param(request, "ids")),
                                    _csv(_str_param(request, "status")))
    )


@api_view(methods=("GET",))
def resource_gantt(request):
    # ``from``/``to`` are required and are reserved words in Python, hence
    # the alias in the original's signature; here they are plain query keys.
    try:
        dt_from = _date_param(request, "from", required=True)
        dt_to = _date_param(request, "to", required=True)
        department_id = _int_param(request, "department_id")
    except _ParamError as exc:
        return exc.response

    kinds = {k.strip() for k in
             (_str_param(request, "kinds", "employee,equipment") or "").split(",")
             if k.strip()}
    return schemas.ResourceGanttResponse.model_validate(
        gantt_service.resource_gantt(dt_from, dt_to, kinds, department_id,
                                     _str_param(request, "search"))
    )


# ─────────────────────────────────────────────────────────────────────────
# Calendar — /calendar/ and /production-calendar/
# ─────────────────────────────────────────────────────────────────────────

def _bounded_range(request, start_key: str, end_key: str):
    """Shared window parsing for the timeline and the production calendar.

    Both default to "this month plus 31 days" and both reject an inverted or
    over-long range with the original's 400 (not 422 — these are range
    *semantics*, which FastAPI could not express as a type either).
    """
    start = _date_param(request, start_key)
    end = _date_param(request, end_key)
    start = start or date.today().replace(day=1)
    end = end or (start + timedelta(days=31))
    if start > end:
        raise _ParamError(json_error(
            f"{start_key} must be before {end_key}", 400))
    if (end - start).days > calendar_service.MAX_RANGE_DAYS:
        raise _ParamError(json_error("Date range is too large", 400))
    return start, end


@api_view(methods=("GET",))
def calendar_timeline(request):
    try:
        start, end = _bounded_range(request, "start", "end")
    except _ParamError as exc:
        return exc.response
    return calendar_service.timeline(request.token, start, end)


@api_view(methods=("GET",))
def _list_events(request):
    try:
        department_id = _int_param(request, "department_id")
    except _ParamError as exc:
        return exc.response
    return [schemas.CalendarEventResponse.model_validate(payload)
            for payload in calendar_service.build_payloads(
                calendar_service.list_events(request.token, department_id))]


@api_view(methods=("POST",), body=schemas.CalendarEventCreate, status=201)
def _create_event(request, data: schemas.CalendarEventCreate):
    event_id = calendar_service.create_event(data.model_dump(),
                                             creator_id=request.token.user_id)
    return schemas.CalendarEventResponse.model_validate(
        calendar_service.reload_payload(event_id))


def events_collection(request):
    if request.method == "GET":
        return _list_events(request)
    if request.method == "POST":
        return _create_event(request)
    return _method_not_allowed(request)


@api_view(methods=("PATCH",), body=schemas.CalendarEventUpdate)
def _update_event(request, event_id: int, data: schemas.CalendarEventUpdate):
    calendar_service.update_event(event_id,
                                  data.model_dump(exclude_unset=True),
                                  request.token)
    return schemas.CalendarEventResponse.model_validate(
        calendar_service.reload_payload(event_id))


@api_view(methods=("DELETE",), status=204)
def _delete_event(request, event_id: int):
    calendar_service.delete_event(event_id, request.token)
    return _no_content()


def event_detail(request, event_id: int):
    if request.method == "PATCH":
        return _update_event(request, event_id=event_id)
    if request.method == "DELETE":
        return _delete_event(request, event_id=event_id)
    return _method_not_allowed(request)


@api_view(methods=("POST",), body=schemas.RsvpUpdate)
def event_rsvp(request, event_id: int, data: schemas.RsvpUpdate):
    calendar_service.rsvp(event_id, request.token.user_id, data.status)
    return schemas.CalendarEventResponse.model_validate(
        calendar_service.reload_payload(event_id))


@api_view(methods=("POST",), body=schemas.EventExceptionBase, status=201)
def event_exceptions(request, event_id: int, data: schemas.EventExceptionBase):
    return schemas.EventExceptionResponse.model_validate(
        calendar_service.create_exception(
            event_id, exception_date=data.exception_date,
            is_cancelled=data.is_cancelled))


@api_view(methods=("DELETE",), status=204)
def event_exception_detail(request, exception_id: int):
    calendar_service.delete_exception(exception_id)
    return _no_content()


@api_view(methods=("GET",))
def calendar_user_options(request):
    """Participant picker — NOT IMPLEMENTED, pending an interface contract.

    The original proxied user-service's ``/api/users/v1/users/options/``
    over HTTP. In the monolith that has to go through
    ``apps.users.interface``, whose agreed §7 surface is
    ``get_user_brief``/``get_users_brief`` — lookup by id, with no search
    form. ``apps.users.services.options_service.list_user_options(query,
    limit)`` already exists and is exactly what this needs, but exposing it
    means adding ``search_user_options`` to the users interface, and a
    consumer may not extend a neighbour's interface unilaterally
    (PLAN.md §1.5 п.3, §7).

    Answers 501 rather than an empty list on purpose: an empty picker looks
    like "no colleagues found" and would be debugged as a data problem. The
    frontend already calls this route (``frontend/src/api/calendar.ts``), so
    the gap is real and belongs on the integration checklist (§8), not
    hidden behind a plausible-looking empty response.
    """
    return json_error(
        "Participant search requires apps.users.interface.search_user_options "
        "(PLAN.md §7 contract extension, pending A↔B agreement)", 501)


@api_view(methods=("GET",))
def production_calendar(request):
    try:
        start, end = _bounded_range(request, "date__gte", "date__lte")
    except _ParamError as exc:
        return exc.response
    return [schemas.ProductionDayResponse.model_validate(row)
            for row in calendar_service.list_production_days(start, end)]


@api_view(methods=("PATCH",), body=schemas.ProductionDayUpdate)
def production_day_detail(request, target_date: str,
                          data: schemas.ProductionDayUpdate):
    try:
        parsed = date.fromisoformat(target_date)
    except ValueError:
        return _param_error("target_date",
                            "Input should be a valid date in YYYY-MM-DD format")
    return schemas.ProductionDayResponse.model_validate(
        calendar_service.update_production_day(parsed, day_type=data.day_type,
                                               note=data.note))
