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

from django.http import HttpResponse

from htqweb.http import api_view, json_error

from . import schemas
from .services import reference_service as ref_svc
from .services import sequence_service
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
