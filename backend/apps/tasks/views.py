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

from django.core.exceptions import PermissionDenied
from django.db import IntegrityError
from django.http import HttpResponse
from django.utils import timezone

from htqweb.http import api_view, json_error

from . import schemas
from .services import block_service
from .services import calendar_service
from .services import contractor_service
from .services import daily_report_service
from .services import equipment_usage_service
from .services import gantt_service
from .services import link_service
from .services import notification_service
from .services import plan_fact_service
from .services import project_service
from .services import reference_service as ref_svc
from .services import resource_service
from .services import roadmap_service
from .services import sequence_service
from .services import site_service
from .services import staff_report_service
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
#
# Reads stay open (every task form needs the list); writes are admin-only.
# These are shared, company-wide dictionaries: one careless rename or
# delete reaches every task at once, and a label deleted here silently
# disappears from tasks that were filed under it.
#
# Task types are deliberately NOT gated the same way — see that section.
# ─────────────────────────────────────────────────────────────────────────

@api_view(methods=("GET",))
def _list_labels(request):
    return [schemas.LabelResponse.model_validate(row)
            for row in ref_svc.list_labels()]


@api_view(methods=("POST",), body=schemas.LabelCreate, status=201, admin=True)
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


@api_view(methods=("PATCH",), body=schemas.LabelUpdate, admin=True)
def _update_label(request, label_id: int, data: schemas.LabelUpdate):
    return schemas.LabelResponse.model_validate(
        ref_svc.update_label(label_id, data.model_dump(exclude_unset=True))
    )


@api_view(methods=("DELETE",), status=204, admin=True)
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
#
# Deliberately NOT admin-gated, unlike labels and equipment: the task form
# creates a type inline (CreateTaskModal's "new type" popover), and the
# business wants that available to everyone who can file a task. Deleting a
# system type is still refused — reference_service raises PermissionDenied
# for ``is_system`` rows.
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
#
# Same split as labels: the list is open (task forms and the resource
# schedule need it), writes are admin-only. This is the company's machinery
# register — renaming or disabling a machine here changes what every
# resource plan shows.
# ─────────────────────────────────────────────────────────────────────────

@api_view(methods=("GET",))
def _list_equipment(request):
    try:
        active_only = _bool_param(request, "active_only", True)
        contractor_id = _int_param(request, "contractor_id")
        category_id = _int_param(request, "category_id")
    except _ParamError as exc:
        return exc.response
    return [schemas.EquipmentResponse.model_validate(
        ref_svc.build_equipment(row))
        for row in ref_svc.list_equipment(
            active_only, ownership=_str_param(request, "ownership"),
            contractor_id=contractor_id, category_id=category_id)]


@api_view(methods=("POST",), body=schemas.EquipmentCreate, status=201, admin=True)
def _create_equipment(request, data: schemas.EquipmentCreate):
    return schemas.EquipmentResponse.model_validate(
        ref_svc.build_equipment(ref_svc.create_equipment(**data.model_dump()))
    )


def equipment_collection(request):
    if request.method == "GET":
        return _list_equipment(request)
    if request.method == "POST":
        return _create_equipment(request)
    return _method_not_allowed(request)


@api_view(methods=("PATCH",), body=schemas.EquipmentUpdate, admin=True)
def _update_equipment(request, equipment_id: int, data: schemas.EquipmentUpdate):
    return schemas.EquipmentResponse.model_validate(
        ref_svc.build_equipment(ref_svc.update_equipment(
            equipment_id, data.model_dump(exclude_unset=True)))
    )


@api_view(methods=("DELETE",), status=204, admin=True)
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
# Плоские справочники — /equipment-categories/, /work-roles/, /volume-types/
#
# Три ручки одинаковой формы, поэтому пара «коллекция + деталь» собирается
# фабрикой, а не копируется трижды. Права те же, что у техники: читать может
# любой (без этих списков не заполнить ни форму задачи, ни план роудмапа),
# писать — админ: это корпоративные словари, и переименование строки меняет
# то, что видят все планы разом.
# ─────────────────────────────────────────────────────────────────────────

def _reference_endpoints(kind: str, create_schema, update_schema,
                         response_schema):
    """Собрать вьюхи коллекции и детали для одного плоского справочника.

    ``kind`` — тот же литерал, что стоит в URL; ``reference_service`` по нему
    и находит таблицу, так что вьюха модель по-прежнему не знает.
    """

    @api_view(methods=("GET",))
    def _list(request):
        try:
            active_only = _bool_param(request, "active_only", True)
        except _ParamError as exc:
            return exc.response
        return [response_schema.model_validate(ref_svc.build_reference_row(row))
                for row in ref_svc.list_reference_rows(kind, active_only)]

    @api_view(methods=("POST",), body=create_schema, status=201, admin=True)
    def _create(request, data):
        try:
            row = ref_svc.create_reference_row(kind, **data.model_dump())
        except ValueError as exc:
            # Занятые слаг или имя — 409, как у типов задач.
            return json_error(str(exc), 409)
        return response_schema.model_validate(ref_svc.build_reference_row(row))

    @api_view(methods=("PATCH",), body=update_schema, admin=True)
    def _update(request, row_id: int, data):
        return response_schema.model_validate(ref_svc.build_reference_row(
            ref_svc.update_reference_row(
                kind, row_id, data.model_dump(exclude_unset=True))))

    @api_view(methods=("DELETE",), status=204, admin=True)
    def _delete(request, row_id: int):
        ref_svc.delete_reference_row(kind, row_id)
        return _no_content()

    def collection(request):
        if request.method == "GET":
            return _list(request)
        if request.method == "POST":
            return _create(request)
        return _method_not_allowed(request)

    def detail(request, row_id: int):
        if request.method == "PATCH":
            return _update(request, row_id=row_id)
        if request.method == "DELETE":
            return _delete(request, row_id=row_id)
        return _method_not_allowed(request)

    return collection, detail


equipment_categories_collection, equipment_category_detail = _reference_endpoints(
    "equipment-categories", schemas.ReferenceRowCreate,
    schemas.ReferenceRowUpdate, schemas.ReferenceRowResponse)

work_roles_collection, work_role_detail = _reference_endpoints(
    "work-roles", schemas.ReferenceRowCreate,
    schemas.ReferenceRowUpdate, schemas.ReferenceRowResponse)

volume_types_collection, volume_type_detail = _reference_endpoints(
    "volume-types", schemas.VolumeTypeCreate,
    schemas.VolumeTypeUpdate, schemas.VolumeTypeResponse)


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
            "roadmap_id": _int_param(request, "roadmap_id"),
            "roadmap_unset": _bool_param(request, "no_roadmap", False),
            "site_id": _int_param(request, "site_id"),
            "site_unset": _bool_param(request, "no_site", False),
            "site_block_id": _int_param(request, "site_block_id"),
            "contractor_id": _int_param(request, "contractor_id"),
            "contractor_unset": _bool_param(request, "own_crew", False),
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
    # ``create_task`` raises ValueError for a site that does not belong to
    # the task's project. Unlike _update_task this view had no except arm at
    # all, so any ValueError from the service reached the client as a 500.
    try:
        task = task_service.create_task(data, user_id=request.token.user_id)
    except ValueError as exc:
        return json_error(str(exc), 400)
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
        site_id = _int_param(request, "site_id")
    except _ParamError as exc:
        return exc.response
    visibility, visibility_department_id = task_service.scope_for(
        request.token, reports=True
    )
    return schemas.TaskStats.model_validate(task_service.task_stats(
        department_id=department_id, project_id=project_id, site_id=site_id,
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
    task = task_service.load_for_action(task_id, request.token)
    return [{"status": status}
            for status in task_service.available_transitions(task)]


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
#
# Every read here goes through ``load_for_action`` first. Without it the
# whole visibility model is decorative: a task the caller cannot list or
# open would still hand over its discussion, its files and its audit trail
# to anyone who guesses the id. ``load_for_action`` answers with 404 (not
# 403) for an out-of-scope task, so these routes cannot be used to probe
# which task ids exist either.
# ─────────────────────────────────────────────────────────────────────────

@api_view(methods=("GET",))
def _list_comments(request, task_id: int):
    task_service.load_for_action(task_id, request.token)
    return task_content_service.list_comments(task_id)


@api_view(methods=("POST",), body=schemas.CommentCreate, status=201)
def _create_comment(request, task_id: int, data: schemas.CommentCreate):
    # Visibility only, deliberately NOT require_soft_edit: commenting is
    # participation, not editing. Anyone who can see the task — including a
    # watcher or a colleague looking at free work in their department — may
    # say something about it. What must not happen is commenting on a task
    # the caller cannot see at all.
    task_service.load_for_action(task_id, request.token)
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
    task_service.load_for_action(task_id, request.token)
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
    task_service.load_for_action(task_id, request.token)
    return task_content_service.list_activity(task_id)


@api_view(methods=("GET",))
def _list_task_volumes(request, task_id: int):
    task_service.load_for_action(task_id, request.token)
    return [schemas.TaskVolumeResponse.model_validate(row)
            for row in task_content_service.list_task_volumes(task_id)]


@api_view(methods=("PUT",), body=schemas.VolumesUpdate)
def _set_task_volumes(request, task_id: int, data: schemas.VolumesUpdate):
    task = task_service.load_for_action(task_id, request.token)
    # Мягкое право, а не полное: «развезли 180 из 250» — это отчёт о ходе
    # работ, ровно то же, что progress_percent, а он под require_soft_edit.
    # Требовать здесь full_edit значило бы запретить исполнителю отчитаться
    # о собственной задаче.
    task_service.require_soft_edit(task, request.token)
    try:
        rows = task_content_service.set_task_volumes(
            task_id, [v.model_dump() for v in data.volumes])
    except ValueError as exc:
        return json_error(str(exc), 422)
    return [schemas.TaskVolumeResponse.model_validate(row) for row in rows]


def task_volumes(request, task_id: int):
    if request.method == "GET":
        return _list_task_volumes(request, task_id=task_id)
    if request.method == "PUT":
        return _set_task_volumes(request, task_id=task_id)
    return _method_not_allowed(request)


# ─────────────────────────────────────────────────────────────────────────
# Ежедневные отчёты — /tasks/{id}/daily-reports , /daily-reports/{id}
#
# Права: заводить отчёт может участник задачи (это отчёт о СВОЕЙ работе,
# то же мягкое право, что у progress). Править и удалять — автор, супервайзер
# задачи или админ: чужую отчётность правит только тот, кто за неё отвечает.
# ─────────────────────────────────────────────────────────────────────────

@api_view(methods=("GET",))
def _list_task_reports(request, task_id: int):
    task_service.load_for_action(task_id, request.token)
    return [schemas.DailyReportResponse.model_validate(row)
            for row in daily_report_service.build_reports(
                daily_report_service.list_reports(task_id=task_id))]


@api_view(methods=("POST",), body=schemas.DailyReportCreate, status=201)
def _create_task_report(request, task_id: int, data: schemas.DailyReportCreate):
    task = task_service.load_for_action(task_id, request.token)
    # Мягкое право: отчёт о выполненном — то же, что progress, а не
    # планирование. Требовать full_edit значило бы запретить исполнителю
    # отчитаться о собственной смене.
    task_service.require_soft_edit(task, request.token)
    try:
        report = daily_report_service.create_report(
            task_id, data.model_dump(), author_id=request.token.user_id)
    except ValueError as exc:
        return json_error(str(exc), 422)
    return schemas.DailyReportResponse.model_validate(
        daily_report_service.build_report(report))


def task_daily_reports(request, task_id: int):
    if request.method == "GET":
        return _list_task_reports(request, task_id=task_id)
    if request.method == "POST":
        return _create_task_report(request, task_id=task_id)
    return _method_not_allowed(request)


def _report_for_write(request, report_id: int):
    """Отчёт, который вызывающий вправе править, иначе исключение.

    Автор правит свой отчёт сам; чужой — только супервайзер задачи или
    админ. Обычного участника задачи сюда НЕ пускаем: цифра выполнения это
    основание для расчётов, и править её за коллегу — не то же самое, что
    завести свою.
    """
    report = daily_report_service.get_report(report_id)
    task_service.load_for_action(report.task_id, request.token)
    token = request.token
    if not (token.is_elevated
            or report.author_id == token.user_id
            or report.task.supervisor_id == token.user_id):
        raise PermissionDenied(
            "Only the report author, the task supervisor or an admin "
            "can change it")
    return report


@api_view(methods=("GET",))
def _get_report(request, report_id: int):
    report = daily_report_service.get_report(report_id)
    task_service.load_for_action(report.task_id, request.token)
    return schemas.DailyReportResponse.model_validate(
        daily_report_service.build_report(report))


@api_view(methods=("PATCH",), body=schemas.DailyReportUpdate)
def _update_report(request, report_id: int, data: schemas.DailyReportUpdate):
    _report_for_write(request, report_id)
    try:
        report = daily_report_service.update_report(
            report_id, data.model_dump(exclude_unset=True),
            editor_id=request.token.user_id)
    except ValueError as exc:
        return json_error(str(exc), 422)
    return schemas.DailyReportResponse.model_validate(
        daily_report_service.build_report(report))


@api_view(methods=("DELETE",), status=204)
def _delete_report(request, report_id: int):
    _report_for_write(request, report_id)
    daily_report_service.delete_report(report_id)
    return _no_content()


def daily_report_detail(request, report_id: int):
    if request.method == "GET":
        return _get_report(request, report_id=report_id)
    if request.method == "PATCH":
        return _update_report(request, report_id=report_id)
    if request.method == "DELETE":
        return _delete_report(request, report_id=report_id)
    return _method_not_allowed(request)


@api_view(methods=("GET",))
def daily_report_revisions(request, report_id: int):
    """Лента версий отчёта. Читают все, кто видит задачу."""
    report = daily_report_service.get_report(report_id)
    task_service.load_for_action(report.task_id, request.token)
    return [schemas.DailyReportRevisionResponse.model_validate(row)
            for row in daily_report_service.build_revisions(
                daily_report_service.list_revisions(report_id))]


@api_view(methods=("GET",))
def daily_report_board(request):
    """Сводка ежедневки: что вызывающий может отчитать за дату ``?date=``.

    Отдельный эндпоинт, а не «список задач + карточка каждой»: объёмы
    приходят только в детальном ответе задачи, и страница ежедневки на 15
    задач стоила бы 16 запросов. Здесь одна выборка на сущность.

    Отбор — по праву ЗАПИСИ (``soft_edit_q``), а не по видимости: строка,
    которую нельзя сохранить, на этой странице не нужна.
    """
    try:
        on = _date_param(request, "date") or timezone.localdate()
    except _ParamError as exc:
        return exc.response
    rows = daily_report_service.reporting_board(
        on=on, user_id=request.token.user_id,
        elevated=request.token.is_elevated)
    return [schemas.DailyReportBoardRow.model_validate(row) for row in rows]


@api_view(methods=("GET",))
def roadmap_daily_reports(request, roadmap_id: int):
    """Отчёты всего пакета работ — лента для карточки роудмапа."""
    try:
        date_from = _date_param(request, "date_from")
        date_to = _date_param(request, "date_to")
    except _ParamError as exc:
        return exc.response
    employee_scope, department_id = roadmap_service.scope_for(request.token)
    roadmap_service.get_roadmap(roadmap_id, employee_scope=employee_scope,
                                department_id=department_id)
    return [schemas.DailyReportResponse.model_validate(row)
            for row in daily_report_service.build_reports(
                daily_report_service.list_reports(
                    roadmap_id=roadmap_id, date_from=date_from,
                    date_to=date_to))]


# ─────────────────────────────────────────────────────────────────────────
# Отчёты по персоналу проекта — /projects/{id}/staff-reports, /staff-reports
#
# Права: смотреть и вести численность проекта может только руководство,
# ответственный за проект и админ. В отличие от ежедневки, где отчёт о
# СВОЕЙ смене заводит любой участник задачи, это управленческие данные по
# объекту целиком, и правило на чтение и на запись здесь одно.
# ─────────────────────────────────────────────────────────────────────────

def _staff_project(request, project_id: int):
    """Проект, чью численность вызывающий вправе смотреть и вести.

    Два гейта, в этом порядке — буквально как в ``_project_for_write``:

    * ``get_project`` со scope вернёт ``Http404`` на проект вне области
      видимости — тот же контракт «404, а не 403», что у задач, чтобы
      нельзя было перечислять проекты чужих отделов;
    * владение: внутри своей области обычный сотрудник ведёт численность
      только своего проекта. Чужой — акт руководства.

    Один helper на чтение и на запись намеренно: правило здесь буквально
    одно, и двум копиям было бы нечему соответствовать, кроме друг друга.
    """
    employee_scope, department_id = project_service.scope_for(request.token)
    project = project_service.get_project(
        project_id, employee_scope=employee_scope, department_id=department_id)
    if not (request.token.is_elevated
            or project.owner_id == request.token.user_id):
        raise PermissionDenied(
            "Only the project owner (or admin) can see project staffing")
    return project


@api_view(methods=("GET",))
def staff_report_projects(request):
    """Проекты, по которым вызывающий вправе вести численность.

    Существует ради селектора на странице: без него фронт предлагал бы
    любой видимый проект и ловил 403 на половине из них. Причина
    расхождения — в токене нет ролей вида ``hr_manager`` (только
    ``is_staff``/``is_superuser``), поэтому роут-гейт фронта шире
    серверного правила, и сузить список должен сервер.
    """
    employee_scope, department_id = project_service.scope_for(request.token)
    projects = [
        project for project in project_service.list_projects(
            employee_scope=employee_scope, department_id=department_id)
        if request.token.is_elevated
        or project.owner_id == request.token.user_id]
    return project_service.build_responses(projects)


@api_view(methods=("GET",))
def project_staff_board(request, project_id: int):
    """Доска численности проекта на ``?date=``: блок × (факт, план, ежедневка).

    Отдельный эндпоинт, а не «список блоков + отчёт каждого»: страница на
    12 блоков стоила бы 25 обращений, потому что план и сверка с ежедневкой
    приходят из других таблиц. Здесь один запрос на сущность.
    """
    project = _staff_project(request, project_id)
    try:
        on = _date_param(request, "date") or timezone.localdate()
    except _ParamError as exc:
        return exc.response
    board = staff_report_service.staff_board(project_id=project.id, on=on)
    return schemas.ProjectStaffBoardResponse.model_validate({
        "project_id": project.id, "project_name": project.name,
        "date": on, **board})


@api_view(methods=("GET",))
def _list_project_staff_reports(request, project_id: int):
    project = _staff_project(request, project_id)
    try:
        date_from = _date_param(request, "date_from")
        date_to = _date_param(request, "date_to")
    except _ParamError as exc:
        return exc.response
    return [schemas.ProjectStaffReportResponse.model_validate(row)
            for row in staff_report_service.build_reports(
                staff_report_service.list_reports(
                    project_id=project.id, date_from=date_from,
                    date_to=date_to))]


@api_view(methods=("POST",), body=schemas.ProjectStaffReportCreate, status=201)
def _create_project_staff_report(request, project_id: int,
                                 data: schemas.ProjectStaffReportCreate):
    project = _staff_project(request, project_id)
    try:
        report = staff_report_service.create_report(
            project.id, data.model_dump(), author_id=request.token.user_id)
    except ValueError as exc:
        return json_error(str(exc), 422)
    return schemas.ProjectStaffReportResponse.model_validate(
        staff_report_service.build_report(report))


def project_staff_reports(request, project_id: int):
    if request.method == "GET":
        return _list_project_staff_reports(request, project_id=project_id)
    if request.method == "POST":
        return _create_project_staff_report(request, project_id=project_id)
    return _method_not_allowed(request)


def _staff_report_for_action(request, report_id: int):
    """Отчёт, который вызывающий вправе открыть, — вместе с проверкой прав."""
    report = staff_report_service.get_report(report_id)
    _staff_project(request, report.project_id)
    return report


@api_view(methods=("GET",))
def _get_staff_report(request, report_id: int):
    report = _staff_report_for_action(request, report_id)
    return schemas.ProjectStaffReportResponse.model_validate(
        staff_report_service.build_report(report))


@api_view(methods=("PATCH",), body=schemas.ProjectStaffReportUpdate)
def _update_staff_report(request, report_id: int,
                         data: schemas.ProjectStaffReportUpdate):
    _staff_report_for_action(request, report_id)
    changes = data.model_dump(exclude_unset=True)
    if changes.get("lines") is not None:
        changes["lines"] = [dict(row) for row in changes["lines"]]
    try:
        report = staff_report_service.update_report(
            report_id, changes, editor_id=request.token.user_id)
    except ValueError as exc:
        return json_error(str(exc), 422)
    return schemas.ProjectStaffReportResponse.model_validate(
        staff_report_service.build_report(report))


@api_view(methods=("DELETE",), status=204)
def _delete_staff_report(request, report_id: int):
    _staff_report_for_action(request, report_id)
    staff_report_service.delete_report(report_id)
    return _no_content()


def staff_report_detail(request, report_id: int):
    if request.method == "GET":
        return _get_staff_report(request, report_id=report_id)
    if request.method == "PATCH":
        return _update_staff_report(request, report_id=report_id)
    if request.method == "DELETE":
        return _delete_staff_report(request, report_id=report_id)
    return _method_not_allowed(request)


@api_view(methods=("GET",))
def staff_report_revisions(request, report_id: int):
    """Лента версий отчёта по персоналу. Читают те же, кто видит отчёт."""
    _staff_report_for_action(request, report_id)
    return [schemas.ProjectStaffRevisionResponse.model_validate(row)
            for row in staff_report_service.build_revisions(
                staff_report_service.list_revisions(report_id))]


# ─────────────────────────────────────────────────────────────────────────
# Task links — /task-links/
# ─────────────────────────────────────────────────────────────────────────

@api_view(methods=("POST",), body=schemas.LinkCreate, status=201)
def _create_link(request, data: schemas.LinkCreate):
    # BOTH endpoints are checked for visibility: a link is a two-way fact
    # (create_link writes the mirror row), so linking a visible task to an
    # invisible one would surface the invisible one's key and summary in
    # the response and on the other task's card. Write permission is
    # required on the source only — that is the side the link is created
    # from, and the side link_detail authorises deletion against.
    source = task_service.load_for_action(data.source_id, request.token)
    task_service.load_for_action(data.target_id, request.token)
    task_service.require_full_edit(source, request.token)
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
    source = task_service.load_for_action(
        link_service.link_source_task_id(link_id), request.token)
    task_service.require_full_edit(source, request.token)
    link_service.delete_link(link_id)
    return _no_content()


# ─────────────────────────────────────────────────────────────────────────
# Contractors — /contractors/ , /contractor-workers/, /contractor-engagements/
#
# Same read-open / write-admin split as the other dictionaries: the task
# form and the equipment register both need the lists, but who counts as a
# subcontractor is an administrative fact.
#
# NOTE: no authorisation depends on these rows yet. ``ContractorWorker.
# user_id`` exists but nothing writes it, and no visibility branch reads a
# contractor — subcontractors have no way into the system on this step.
# ─────────────────────────────────────────────────────────────────────────

@api_view(methods=("GET",))
def _list_contractors(request):
    return [schemas.ContractorResponse.model_validate(
        contractor_service.build_contractor(row))
        for row in contractor_service.list_contractors(
            status=_str_param(request, "status"),
            search=_str_param(request, "search"))]


@api_view(methods=("POST",), body=schemas.ContractorCreate, status=201,
          admin=True)
def _create_contractor(request, data: schemas.ContractorCreate):
    return schemas.ContractorResponse.model_validate(
        contractor_service.build_contractor(
            contractor_service.create_contractor(data.model_dump())))


def contractors_collection(request):
    if request.method == "GET":
        return _list_contractors(request)
    if request.method == "POST":
        return _create_contractor(request)
    return _method_not_allowed(request)


@api_view(methods=("GET",))
def _get_contractor(request, contractor_id: int):
    return schemas.ContractorResponse.model_validate(
        contractor_service.build_contractor(
            contractor_service.get_contractor(contractor_id)))


@api_view(methods=("PATCH",), body=schemas.ContractorUpdate, admin=True)
def _update_contractor(request, contractor_id: int,
                       data: schemas.ContractorUpdate):
    return schemas.ContractorResponse.model_validate(
        contractor_service.build_contractor(
            contractor_service.update_contractor(
                contractor_id, data.model_dump(exclude_unset=True))))


@api_view(methods=("DELETE",), status=204, admin=True)
def _delete_contractor(request, contractor_id: int):
    try:
        contractor_service.delete_contractor(contractor_id)
    except contractor_service.ContractorInUse as exc:
        return json_error(str(exc), 409)
    return _no_content()


def contractor_detail(request, contractor_id: int):
    if request.method == "GET":
        return _get_contractor(request, contractor_id=contractor_id)
    if request.method == "PATCH":
        return _update_contractor(request, contractor_id=contractor_id)
    if request.method == "DELETE":
        return _delete_contractor(request, contractor_id=contractor_id)
    return _method_not_allowed(request)


@api_view(methods=("GET",))
def _list_contractor_workers(request, contractor_id: int):
    contractor_service.get_contractor(contractor_id)
    return [schemas.ContractorWorkerResponse.model_validate(
        contractor_service.build_worker(row))
        for row in contractor_service.list_workers(
            contractor_id=contractor_id,
            active_only=_bool_param(request, "active_only", True))]


@api_view(methods=("POST",), body=schemas.ContractorWorkerCreate, status=201,
          admin=True)
def _create_contractor_worker(request, contractor_id: int,
                              data: schemas.ContractorWorkerCreate):
    return schemas.ContractorWorkerResponse.model_validate(
        contractor_service.build_worker(
            contractor_service.create_worker(contractor_id,
                                             data.model_dump())))


def contractor_workers(request, contractor_id: int):
    if request.method == "GET":
        return _list_contractor_workers(request, contractor_id=contractor_id)
    if request.method == "POST":
        return _create_contractor_worker(request, contractor_id=contractor_id)
    return _method_not_allowed(request)


@api_view(methods=("PATCH",), body=schemas.ContractorWorkerUpdate, admin=True)
def _update_contractor_worker(request, worker_id: int,
                              data: schemas.ContractorWorkerUpdate):
    return schemas.ContractorWorkerResponse.model_validate(
        contractor_service.build_worker(
            contractor_service.update_worker(
                worker_id, data.model_dump(exclude_unset=True))))


@api_view(methods=("DELETE",), status=204, admin=True)
def _delete_contractor_worker(request, worker_id: int):
    contractor_service.delete_worker(worker_id)
    return _no_content()


def contractor_worker_detail(request, worker_id: int):
    if request.method == "PATCH":
        return _update_contractor_worker(request, worker_id=worker_id)
    if request.method == "DELETE":
        return _delete_contractor_worker(request, worker_id=worker_id)
    return _method_not_allowed(request)


@api_view(methods=("GET",))
def _list_engagements(request):
    try:
        contractor_id = _int_param(request, "contractor_id")
        project_id = _int_param(request, "project_id")
        site_id = _int_param(request, "site_id")
        roadmap_id = _int_param(request, "roadmap_id")
    except _ParamError as exc:
        return exc.response
    return [schemas.ContractorEngagementResponse.model_validate(
        contractor_service.build_engagement(row))
        for row in contractor_service.list_engagements(
            contractor_id=contractor_id, project_id=project_id,
            site_id=site_id, roadmap_id=roadmap_id,
            active_only=_bool_param(request, "active_only", False))]


@api_view(methods=("POST",), body=schemas.ContractorEngagementCreate,
          status=201, admin=True)
def _create_engagement(request, data: schemas.ContractorEngagementCreate):
    try:
        row = contractor_service.create_engagement(data.model_dump())
    except ValueError as exc:
        return json_error(str(exc), 400)
    return schemas.ContractorEngagementResponse.model_validate(
        contractor_service.build_engagement(row))


def engagements_collection(request):
    if request.method == "GET":
        return _list_engagements(request)
    if request.method == "POST":
        return _create_engagement(request)
    return _method_not_allowed(request)


@api_view(methods=("PATCH",), body=schemas.ContractorEngagementUpdate,
          admin=True)
def _update_engagement(request, engagement_id: int,
                       data: schemas.ContractorEngagementUpdate):
    try:
        row = contractor_service.update_engagement(
            engagement_id, data.model_dump(exclude_unset=True))
    except ValueError as exc:
        return json_error(str(exc), 400)
    return schemas.ContractorEngagementResponse.model_validate(
        contractor_service.build_engagement(row))


@api_view(methods=("DELETE",), status=204, admin=True)
def _delete_engagement(request, engagement_id: int):
    contractor_service.delete_engagement(engagement_id)
    return _no_content()


def engagement_detail(request, engagement_id: int):
    if request.method == "PATCH":
        return _update_engagement(request, engagement_id=engagement_id)
    if request.method == "DELETE":
        return _delete_engagement(request, engagement_id=engagement_id)
    return _method_not_allowed(request)


# ─────────────────────────────────────────────────────────────────────────
# Sites — /sites/ , /sites/{id}
#
# Same split as the other dictionaries: the list is open (every task form
# and every filter needs it), writes are admin-only. An object is an axis
# of planning and reporting — renaming or closing one changes what every
# schedule and report shows.
# ─────────────────────────────────────────────────────────────────────────

@api_view(methods=("GET",))
def _list_sites(request):
    return [schemas.SiteResponse.model_validate(row)
            for row in site_service.build_responses(site_service.list_sites(
                status=_str_param(request, "status"),
                search=_str_param(request, "search")))]


@api_view(methods=("POST",), body=schemas.SiteCreate, status=201, admin=True)
def _create_site(request, data: schemas.SiteCreate):
    return schemas.SiteResponse.model_validate(
        site_service.build_response(site_service.create_site(data.model_dump()))
    )


def sites_collection(request):
    if request.method == "GET":
        return _list_sites(request)
    if request.method == "POST":
        return _create_site(request)
    return _method_not_allowed(request)


@api_view(methods=("GET",))
def _get_site(request, site_id: int):
    return schemas.SiteResponse.model_validate(
        site_service.build_response(site_service.get_site(site_id)))


@api_view(methods=("PATCH",), body=schemas.SiteUpdate, admin=True)
def _update_site(request, site_id: int, data: schemas.SiteUpdate):
    return schemas.SiteResponse.model_validate(
        site_service.build_response(site_service.update_site(
            site_id, data.model_dump(exclude_unset=True)))
    )


@api_view(methods=("DELETE",), status=204, admin=True)
def _delete_site(request, site_id: int):
    try:
        site_service.delete_site(site_id)
    except site_service.SiteInUse as exc:
        # 409, not 400: the request is well-formed, the object's state is
        # what forbids it. The message names the counts so the UI can tell
        # the user what to detach first.
        return json_error(str(exc), 409)
    return _no_content()


def site_detail(request, site_id: int):
    if request.method == "GET":
        return _get_site(request, site_id=site_id)
    if request.method == "PATCH":
        return _update_site(request, site_id=site_id)
    if request.method == "DELETE":
        return _delete_site(request, site_id=site_id)
    return _method_not_allowed(request)


@api_view(methods=("GET",))
def site_tasks(request, site_id: int):
    """Tasks on one object — visibility-scoped like every other task list."""
    site_service.get_site(site_id)          # 404 first for an unknown object
    visibility, department_id = task_service.scope_for(request.token)
    tasks = task_service.list_tasks(
        limit=1000, site_id=site_id,
        visibility=visibility,
        visibility_user_id=request.token.user_id,
        visibility_department_id=department_id,
    )
    return task_response.build_list(tasks)


# ─────────────────────────────────────────────────────────────────────────
# Блоки объекта — /sites/{id}/blocks , /blocks/{id} , /blocks/{id}/volumes
#
# Права как у объектов: читать может любой (без списка блоков не заполнить
# форму задачи), писать — админ. Блок это деление площадки, а не рабочая
# запись: его заводят один раз при разбивке объекта.
# ─────────────────────────────────────────────────────────────────────────

@api_view(methods=("GET",))
def _list_site_blocks(request, site_id: int):
    site_service.get_site(site_id)          # 404 раньше пустого списка
    return [schemas.SiteBlockResponse.model_validate(row)
            for row in block_service.build_blocks(
                block_service.list_blocks(
                    site_id, status=_str_param(request, "status")))]


@api_view(methods=("POST",), body=schemas.SiteBlockCreate, status=201,
          admin=True)
def _create_site_block(request, site_id: int, data: schemas.SiteBlockCreate):
    site_service.get_site(site_id)
    try:
        block = block_service.create_block(site_id, data.model_dump())
    except IntegrityError:
        # uq_site_block_name / uq_site_block_code: «блок 1» на этой площадке
        # уже есть. 409, а не 500 — запрос корректен, конфликтует состояние.
        return json_error("Блок с таким названием или кодом уже есть "
                          "на этом объекте", 409)
    return schemas.SiteBlockResponse.model_validate(
        block_service.build_block(block))


def site_blocks_collection(request, site_id: int):
    if request.method == "GET":
        return _list_site_blocks(request, site_id=site_id)
    if request.method == "POST":
        return _create_site_block(request, site_id=site_id)
    return _method_not_allowed(request)


@api_view(methods=("GET",))
def _get_block(request, block_id: int):
    block = block_service.get_block(block_id)
    return schemas.SiteBlockResponse.model_validate(block_service.build_block(
        block, volumes=block_service.list_block_volumes(block_id)))


@api_view(methods=("PATCH",), body=schemas.SiteBlockUpdate, admin=True)
def _update_block(request, block_id: int, data: schemas.SiteBlockUpdate):
    try:
        block = block_service.update_block(
            block_id, data.model_dump(exclude_unset=True))
    except IntegrityError:
        return json_error("Блок с таким названием или кодом уже есть "
                          "на этом объекте", 409)
    return schemas.SiteBlockResponse.model_validate(block_service.build_block(
        block, volumes=block_service.list_block_volumes(block_id)))


@api_view(methods=("DELETE",), status=204, admin=True)
def _delete_block(request, block_id: int):
    try:
        block_service.delete_block(block_id)
    except block_service.BlockInUse as exc:
        return json_error(str(exc), 409)
    return _no_content()


def block_detail(request, block_id: int):
    if request.method == "GET":
        return _get_block(request, block_id=block_id)
    if request.method == "PATCH":
        return _update_block(request, block_id=block_id)
    if request.method == "DELETE":
        return _delete_block(request, block_id=block_id)
    return _method_not_allowed(request)


@api_view(methods=("GET",))
def _list_block_volumes(request, block_id: int):
    block_service.get_block(block_id)
    return [schemas.VolumeResponse.model_validate(block_service.build_volume(row))
            for row in block_service.list_block_volumes(block_id)]


@api_view(methods=("PUT",), body=schemas.VolumesUpdate, admin=True)
def _set_block_volumes(request, block_id: int, data: schemas.VolumesUpdate):
    try:
        rows = block_service.set_block_volumes(
            block_id, [v.model_dump() for v in data.volumes])
    except ValueError as exc:
        # Несуществующий вид объёма. Проверяется в сервисе явно, а не через
        # FK: тот поднимает IntegrityError на коммите, когда вьюха уже
        # ответила 200 (см. block_service.require_volume_types).
        return json_error(str(exc), 422)
    return [schemas.VolumeResponse.model_validate(block_service.build_volume(row))
            for row in rows]


def block_volumes(request, block_id: int):
    if request.method == "GET":
        return _list_block_volumes(request, block_id=block_id)
    if request.method == "PUT":
        return _set_block_volumes(request, block_id=block_id)
    return _method_not_allowed(request)


@api_view(methods=("GET",))
def block_progress(request, block_id: int):
    """Выполнение блока в штуках, а не в статусах задач."""
    block_service.get_block(block_id)
    return schemas.BlockProgressResponse.model_validate(
        block_service.block_progress(block_id))


@api_view(methods=("GET",))
def _list_project_sites(request, project_id: int):
    return [schemas.ProjectSiteRef.model_validate(
        site_service.build_project_site_ref(link))
        for link in site_service.list_project_sites(project_id)]


@api_view(methods=("PUT",), body=schemas.ProjectSitesUpdate, admin=True)
def _set_project_sites(request, project_id: int,
                       data: schemas.ProjectSitesUpdate):
    try:
        links = site_service.set_project_sites(
            project_id, data.site_ids, data.primary_site_id)
    except ValueError as exc:
        return json_error(str(exc), 400)
    return [schemas.ProjectSiteRef.model_validate(
        site_service.build_project_site_ref(link)) for link in links]


def project_sites(request, project_id: int):
    if request.method == "GET":
        return _list_project_sites(request, project_id=project_id)
    if request.method == "PUT":
        return _set_project_sites(request, project_id=project_id)
    return _method_not_allowed(request)


# ─────────────────────────────────────────────────────────────────────────
# Projects — /projects/
# ─────────────────────────────────────────────────────────────────────────

@api_view(methods=("GET",))
def _list_projects(request):
    employee_scope, department_id = project_service.scope_for(request.token)
    return project_service.build_responses(project_service.list_projects(
        employee_scope=employee_scope, department_id=department_id))


@api_view(methods=("POST",), body=schemas.ProjectCreate, status=201, admin=True)
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


def _project_for_write(request, project_id: int):
    """Load a project the caller may edit, or raise.

    Two gates, in this order and for different reasons:

    * ``get_project`` with the caller's scope answers ``Http404`` for a
      project outside it — same "404, not 403" contract the task routes use,
      so this cannot enumerate projects of other departments.
    * ownership: inside their own scope a regular employee may still only
      touch a project they own. Editing someone else's roadmap is an
      elevated act.
    """
    employee_scope, department_id = project_service.scope_for(request.token)
    project = project_service.get_project(
        project_id, employee_scope=employee_scope, department_id=department_id)
    if not (request.token.is_elevated
            or project.owner_id == request.token.user_id):
        raise PermissionDenied("Only the project owner (or admin) can change it")
    return project


@api_view(methods=("PATCH",), body=schemas.ProjectUpdate)
def _update_project(request, project_id: int, data: schemas.ProjectUpdate):
    _project_for_write(request, project_id)
    return project_service.build_response(project_service.update_project(
        project_id, data.model_dump(exclude_unset=True)))


@api_view(methods=("DELETE",), status=204)
def _delete_project(request, project_id: int):
    _project_for_write(request, project_id)
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


# ─────────────────────────────────────────────────────────────────────────
# Роудмапы — /roadmaps/ , /roadmaps/{id}[/tasks|/metrics]
#
# Права зеркалят проекты: смотреть — по своей области видимости, править —
# владелец или админ. Роудмап это план работ, а не рабочая запись, и
# переписать чужой пакет — действие того же веса, что переписать проект.
# ─────────────────────────────────────────────────────────────────────────

@api_view(methods=("GET",))
def _list_roadmaps(request):
    try:
        project_id = _int_param(request, "project_id")
        site_id = _int_param(request, "site_id")
        block_id = _int_param(request, "block_id")
    except _ParamError as exc:
        return exc.response
    employee_scope, department_id = roadmap_service.scope_for(request.token)
    return [schemas.RoadmapResponse.model_validate(row)
            for row in roadmap_service.build_responses(
                roadmap_service.list_roadmaps(
                    employee_scope=employee_scope, department_id=department_id,
                    project_id=project_id, site_id=site_id, block_id=block_id,
                    status=_str_param(request, "status")))]


@api_view(methods=("POST",), body=schemas.RoadmapCreate, status=201, admin=True)
def _create_roadmap(request, data: schemas.RoadmapCreate):
    try:
        roadmap = roadmap_service.create_roadmap(
            data.model_dump(), creator_id=request.token.user_id)
    except ValueError as exc:
        # Блок не из проекта / несуществующая ссылка — 400, как у задач.
        return json_error(str(exc), 400)
    except IntegrityError:
        return json_error("Роудмап с таким названием уже есть "
                          "на этом блоке проекта", 409)
    return schemas.RoadmapResponse.model_validate(
        roadmap_service.build_response(roadmap))


def roadmaps_collection(request):
    if request.method == "GET":
        return _list_roadmaps(request)
    if request.method == "POST":
        return _create_roadmap(request)
    return _method_not_allowed(request)


def _roadmap_for_write(request, roadmap_id: int):
    """Роудмап, который вызывающий вправе править, иначе исключение.

    Те же две калитки и в том же порядке, что у ``_project_for_write``:
    сначала 404 для чужой области видимости (чтобы ручка не работала
    перечислителем), затем владение.
    """
    employee_scope, department_id = roadmap_service.scope_for(request.token)
    roadmap = roadmap_service.get_roadmap(
        roadmap_id, employee_scope=employee_scope, department_id=department_id)
    if not (request.token.is_elevated
            or roadmap.owner_id == request.token.user_id):
        raise PermissionDenied(
            "Only the roadmap owner (or admin) can change it")
    return roadmap


@api_view(methods=("GET",))
def _get_roadmap(request, roadmap_id: int):
    employee_scope, department_id = roadmap_service.scope_for(request.token)
    return schemas.RoadmapResponse.model_validate(
        roadmap_service.build_response(roadmap_service.get_roadmap(
            roadmap_id, employee_scope=employee_scope,
            department_id=department_id)))


@api_view(methods=("PATCH",), body=schemas.RoadmapUpdate)
def _update_roadmap(request, roadmap_id: int, data: schemas.RoadmapUpdate):
    _roadmap_for_write(request, roadmap_id)
    try:
        roadmap = roadmap_service.update_roadmap(
            roadmap_id, data.model_dump(exclude_unset=True))
    except ValueError as exc:
        return json_error(str(exc), 400)
    except IntegrityError:
        return json_error("Роудмап с таким названием уже есть "
                          "на этом блоке проекта", 409)
    return schemas.RoadmapResponse.model_validate(
        roadmap_service.build_response(roadmap))


@api_view(methods=("DELETE",), status=204)
def _delete_roadmap(request, roadmap_id: int):
    _roadmap_for_write(request, roadmap_id)
    try:
        roadmap_service.delete_roadmap(roadmap_id)
    except roadmap_service.RoadmapInUse as exc:
        # 409, как у объекта и блока: запрос корректен, мешает состояние.
        return json_error(str(exc), 409)
    return _no_content()


def roadmap_detail(request, roadmap_id: int):
    if request.method == "GET":
        return _get_roadmap(request, roadmap_id=roadmap_id)
    if request.method == "PATCH":
        return _update_roadmap(request, roadmap_id=roadmap_id)
    if request.method == "DELETE":
        return _delete_roadmap(request, roadmap_id=roadmap_id)
    return _method_not_allowed(request)


@api_view(methods=("GET",))
def roadmap_tasks(request, roadmap_id: int):
    """Плоский список задач пакета — дерево строит UI, как и у проектов."""
    employee_scope, department_id = roadmap_service.scope_for(request.token)
    roadmap_service.get_roadmap(roadmap_id, employee_scope=employee_scope,
                                department_id=department_id)
    # Видеть роудмап — не значит видеть каждую его задачу: та же тройка
    # видимости, что у плоского списка (см. project_tasks).
    visibility, visibility_department_id = task_service.scope_for(request.token)
    tasks = task_service.list_tasks(
        limit=1000, roadmap_id=roadmap_id,
        visibility=visibility,
        visibility_user_id=request.token.user_id,
        visibility_department_id=visibility_department_id,
    )
    return task_response.build_list(tasks)


@api_view(methods=("GET",))
def roadmap_metrics(request, roadmap_id: int):
    """План против факта по трём осям доски: срок, люди, техника."""
    employee_scope, department_id = roadmap_service.scope_for(request.token)
    roadmap = roadmap_service.get_roadmap(
        roadmap_id, employee_scope=employee_scope, department_id=department_id)
    return schemas.RoadmapMetricsResponse.model_validate(
        roadmap_service.roadmap_metrics(roadmap))


@api_view(methods=("GET",))
def project_tasks(request, project_id: int):
    """Flat task list for a project — the UI builds the tree itself."""
    employee_scope, department_id = project_service.scope_for(request.token)
    # 404s first if the project is out of scope, so this cannot be used to
    # enumerate tasks of a project the caller may not see.
    project_service.get_project(project_id, employee_scope=employee_scope,
                                department_id=department_id)
    # Seeing the project is NOT seeing every task in it: narrowing by
    # department alone still handed over tasks the caller has no part in.
    # Same visibility triple as the flat list endpoint.
    visibility, visibility_department_id = task_service.scope_for(request.token)
    tasks = task_service.list_tasks(
        limit=1000, project_id=project_id,
        visibility=visibility,
        visibility_user_id=request.token.user_id,
        visibility_department_id=visibility_department_id,
    )
    return task_response.build_list(tasks)


# ─────────────────────────────────────────────────────────────────────────
# Ресурсы — /assignments/ (факт именами) и /resource-requirements/ (план)
#
# Обе ручки принимают ЛИБО task_id, ЛИБО roadmap_id. Права берутся от цели:
# у задачи — full_edit (бронирование человека или машины это планирование,
# а не отчёт о ходе работ, иначе любой исполнитель переназначал бы технику
# бригады), у роудмапа — та же калитка владельца, что у его карточки.
# ─────────────────────────────────────────────────────────────────────────

def _authorise_resource_target(request, task_id: int | None,
                               roadmap_id: int | None):
    """Проверить право писать ресурсы указанной цели."""
    if task_id is not None:
        task = task_service.load_for_action(task_id, request.token)
        task_service.require_full_edit(task, request.token)
    else:
        _roadmap_for_write(request, roadmap_id)


def _read_resource_target(request, task_id: int | None,
                          roadmap_id: int | None):
    """Проверить право ЧИТАТЬ ресурсы цели — только видимость, без правки."""
    if task_id is not None:
        task_service.load_for_action(task_id, request.token)
    else:
        employee_scope, department_id = roadmap_service.scope_for(request.token)
        roadmap_service.get_roadmap(roadmap_id, employee_scope=employee_scope,
                                    department_id=department_id)


@api_view(methods=("GET",))
def _list_assignments(request):
    try:
        task_id = _int_param(request, "task_id")
        roadmap_id = _int_param(request, "roadmap_id")
    except _ParamError as exc:
        return exc.response
    if (task_id is None) == (roadmap_id is None):
        # ``task_id`` was required in the original; ``roadmap_id`` is the
        # new alternative. Exactly one, never both.
        return json_error([{"type": "missing", "loc": ["query", "task_id"],
                            "msg": "Provide exactly one of task_id, roadmap_id"}],
                          422)
    _read_resource_target(request, task_id, roadmap_id)
    return [resource_service.build_allocation(row)
            for row in resource_service.list_allocations(
                task_id=task_id, roadmap_id=roadmap_id)]


@api_view(methods=("POST",), body=schemas.AssignmentCreate, status=201)
def _create_assignment(request, data: schemas.AssignmentCreate):
    _authorise_resource_target(request, data.task_id, data.roadmap_id)
    try:
        return resource_service.build_allocation(
            resource_service.create_allocation(data))
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
    task_id, roadmap_id = resource_service.allocation_target(assignment_id)
    _authorise_resource_target(request, task_id, roadmap_id)
    resource_service.delete_allocation(assignment_id)
    return _no_content()


@api_view(methods=("GET",))
def _list_requirements(request):
    try:
        task_id = _int_param(request, "task_id")
        roadmap_id = _int_param(request, "roadmap_id")
    except _ParamError as exc:
        return exc.response
    if (task_id is None) == (roadmap_id is None):
        return json_error([{"type": "missing", "loc": ["query", "roadmap_id"],
                            "msg": "Provide exactly one of task_id, roadmap_id"}],
                          422)
    _read_resource_target(request, task_id, roadmap_id)
    return [schemas.ResourceRequirementResponse.model_validate(row)
            for row in resource_service.build_requirements(
                resource_service.list_requirements(
                    task_id=task_id, roadmap_id=roadmap_id))]


@api_view(methods=("POST",), body=schemas.ResourceRequirementCreate,
          status=201)
def _create_requirement(request, data: schemas.ResourceRequirementCreate):
    _authorise_resource_target(request, data.task_id, data.roadmap_id)
    try:
        row = resource_service.create_requirement(data.model_dump())
    except ValueError as exc:
        return json_error(str(exc), 422)
    return schemas.ResourceRequirementResponse.model_validate(
        resource_service.build_requirement(row))


def requirements_collection(request):
    if request.method == "GET":
        return _list_requirements(request)
    if request.method == "POST":
        return _create_requirement(request)
    return _method_not_allowed(request)


@api_view(methods=("PATCH",), body=schemas.ResourceRequirementUpdate)
def _update_requirement(request, requirement_id: int,
                        data: schemas.ResourceRequirementUpdate):
    row = resource_service.get_requirement(requirement_id)
    _authorise_resource_target(request, row.task_id, row.roadmap_id)
    return schemas.ResourceRequirementResponse.model_validate(
        resource_service.build_requirement(
            resource_service.update_requirement(
                requirement_id, data.model_dump(exclude_unset=True))))


@api_view(methods=("DELETE",), status=204)
def _delete_requirement(request, requirement_id: int):
    row = resource_service.get_requirement(requirement_id)
    _authorise_resource_target(request, row.task_id, row.roadmap_id)
    resource_service.delete_requirement(requirement_id)
    return _no_content()


def requirement_detail(request, requirement_id: int):
    if request.method == "PATCH":
        return _update_requirement(request, requirement_id=requirement_id)
    if request.method == "DELETE":
        return _delete_requirement(request, requirement_id=requirement_id)
    return _method_not_allowed(request)


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
    try:
        project_id = _int_param(request, "project_id")
        site_id = _int_param(request, "site_id")
        roadmap_id = _int_param(request, "roadmap_id")
        site_block_id = _int_param(request, "site_block_id")
    except _ParamError as exc:
        return exc.response
    return schemas.ReportsGanttResponse.model_validate(
        gantt_service.reports_gantt(_csv_ints(_str_param(request, "ids")),
                                    _csv(_str_param(request, "status")),
                                    project_id, site_id, roadmap_id,
                                    site_block_id)
    )


@api_view(methods=("GET",))
def resource_gantt(request):
    # ``from``/``to`` are required and are reserved words in Python, hence
    # the alias in the original's signature; here they are plain query keys.
    try:
        dt_from = _date_param(request, "from", required=True)
        dt_to = _date_param(request, "to", required=True)
        department_id = _int_param(request, "department_id")
        project_id = _int_param(request, "project_id")
        site_id = _int_param(request, "site_id")
    except _ParamError as exc:
        return exc.response

    kinds = {k.strip() for k in
             (_str_param(request, "kinds", "employee,equipment") or "").split(",")
             if k.strip()}
    return schemas.ResourceGanttResponse.model_validate(
        gantt_service.resource_gantt(dt_from, dt_to, kinds, department_id,
                                     _str_param(request, "search"),
                                     project_id, site_id)
    )


# ─────────────────────────────────────────────────────────────────────────
# План/факт — /plan-fact/project/{id} , /plan-fact/roadmap/{id}
#
# Отчётная дата задаётся ``?date=`` и по умолчанию сегодня. Она не
# косметика: прогноз и проценты на 5 июня и на 20 июня — разные ответы, и
# оба должны быть доступны.
# ─────────────────────────────────────────────────────────────────────────

@api_view(methods=("GET",))
def project_plan_fact(request, project_id: int):
    """Дерево проект → площадки → блоки → роудмапы на отчётную дату."""
    try:
        on = _date_param(request, "date") or date.today()
    except _ParamError as exc:
        return exc.response
    employee_scope, department_id = project_service.scope_for(request.token)
    project = project_service.get_project(
        project_id, employee_scope=employee_scope, department_id=department_id)
    return schemas.PlanFactNode.model_validate(
        plan_fact_service.project_plan_fact(project, on))


@api_view(methods=("GET",))
def roadmap_plan_fact(request, roadmap_id: int):
    """То же для пакета работ + его задачи и серии по дням."""
    try:
        on = _date_param(request, "date") or date.today()
    except _ParamError as exc:
        return exc.response
    employee_scope, department_id = roadmap_service.scope_for(request.token)
    roadmap = roadmap_service.get_roadmap(
        roadmap_id, employee_scope=employee_scope, department_id=department_id)
    return schemas.PlanFactNode.model_validate(
        plan_fact_service.roadmap_plan_fact(roadmap, on))


@api_view(methods=("GET",))
def equipment_usage(request):
    """Учёт задействования техники: что занято на дату D и история интервалов.

    Узел иерархии задаётся ровно одним из ``project_id`` / ``site_id`` /
    ``block_id`` / ``roadmap_id`` / ``task_id``; без него ответ был бы «по
    всей компании» — вопрос, которого никто не задаёт, но который стоил бы
    полного скана.
    """
    try:
        target_date = _date_param(request, "date") or date.today()
        date_from = _date_param(request, "date_from") or target_date
        date_to = _date_param(request, "date_to") or target_date
        category_id = _int_param(request, "category_id")
        scope = {
            "project_id": _int_param(request, "project_id"),
            "site_id": _int_param(request, "site_id"),
            "block_id": _int_param(request, "block_id"),
            "roadmap_id": _int_param(request, "roadmap_id"),
            "task_id": _int_param(request, "task_id"),
        }
    except _ParamError as exc:
        return exc.response

    given = {key: value for key, value in scope.items() if value is not None}
    if len(given) != 1:
        return json_error([{"type": "missing", "loc": ["query", "project_id"],
                            "msg": "Provide exactly one of project_id, "
                                   "site_id, block_id, roadmap_id, task_id"}],
                          422)
    if date_to < date_from:
        return json_error("date_to раньше date_from", 422)

    return schemas.EquipmentUsageResponse.model_validate({
        "engaged_on": target_date,
        "engaged": equipment_usage_service.engaged_on(target_date, **given),
        "history": equipment_usage_service.usage_history(
            date_from, date_to, category_id=category_id, **given),
    })


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
