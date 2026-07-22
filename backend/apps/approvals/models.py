"""Approvals domain models — idiomatic Django, built from scratch in ``public``.

Ported from the ``services/requests`` FastAPI microservice (SQLAlchemy +
alembic). Per PLAN.md §3 alembic parity is explicitly NOT a goal:
table/constraint/index names are Django-generated, PG enums become
``TextChoices``, and the schema comes from a natural ``makemigrations``.

Two tables from the original are deliberately **absent** (decision Р2,
PLAN.md §6.2): ``request_users`` and ``request_departments`` were replicas
synced over Redis pub/sub from user-service and hr-service. In the monolith
there is nothing to replicate — apps talk through ``interface.py``. Every
column that was a FK into one of those two is a plain integer id here
(``initiator_id``, ``approver_id``, ``owner_id``, ``user_id``, …), resolved
through ``apps.users.interface`` / ``apps.hr.interface``.

Three composite primary keys from the original (``request_watchers``,
``request_project_members``, ``request_stats_daily``) become a surrogate
``id`` plus a ``UniqueConstraint`` on the original key. None of those tuples
is ever used as an identifier by the API — watchers are addressed by
``user_id`` within a request, members by ``user_id`` within a project, and
stats rows are only ever aggregated — so this is invisible to clients while
keeping every row addressable by the admin and by a plain ORM ``pk``.

``JSONB`` columns (``schema_json``, ``workflow_json``, ``form_values_json``,
``config_json``, ``columns_json``, ``data_json``, ``payload``) stay JSON:
they hold the form builder's and workflow engine's documents, which are
genuinely schemaless. Django's ``JSONField`` is ``jsonb`` on Postgres.
"""

from django.db import models
from django.db.models.functions import Now


# ─────────────────────────────────────────────────────────────────────────
# Enumerations
# ─────────────────────────────────────────────────────────────────────────

class RequestStatus(models.TextChoices):
    DRAFT = "draft"
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    RETURNED = "returned"


class ApprovalActionType(models.TextChoices):
    APPROVE = "approve"
    REJECT = "reject"
    REQUEST_CHANGES = "request_changes"
    DELEGATE = "delegate"
    AUTO_SKIP = "auto_skip"


class ProjectStatus(models.TextChoices):
    ACTIVE = "active"
    COMPLETED = "completed"
    ARCHIVED = "archived"


class ProjectMemberRole(models.TextChoices):
    ADMIN = "admin"
    MEMBER = "member"
    VIEWER = "viewer"


class TemplateStatus(models.TextChoices):
    """Template lifecycle.

    ``inactive`` keeps the template visible to admins in Шаблоны but blocks
    submitting; ``deleted`` hides it and blocks the form while preserving its
    data table and reference data — which is why this is a status column and
    not a real delete.
    """

    ACTIVE = "active"
    INACTIVE = "inactive"
    DELETED = "deleted"


# Statuses that mean the request is finished and will not move again.
TERMINAL_STATUSES = frozenset({RequestStatus.APPROVED, RequestStatus.REJECTED,
                               RequestStatus.CANCELLED})


# ─────────────────────────────────────────────────────────────────────────
# Projects
# ─────────────────────────────────────────────────────────────────────────

class RequestProject(models.Model):
    """Project stub, local to this domain.

    The original named its table ``request_projects`` precisely to avoid
    colliding with task-service's ``projects`` in the shared schema. Django's
    app-prefixed names (``approvals_requestproject`` vs
    ``tasks_project``) make that collision impossible by construction, but
    the two remain separate models on purpose: they are different concepts
    owned by different domains, and PLAN.md §1.5 forbids a cross-app FK.
    """

    name = models.CharField(max_length=200, unique=True)
    description = models.TextField(default="", blank=True, db_default="")
    status = models.CharField(max_length=20, choices=ProjectStatus.choices,
                              default=ProjectStatus.ACTIVE,
                              db_default=ProjectStatus.ACTIVE)
    color = models.CharField(max_length=20, default="#3b82f6",
                             db_default="#3b82f6")
    budget_limit = models.DecimalField(max_digits=18, decimal_places=2,
                                       null=True, blank=True)
    currency = models.CharField(max_length=3, default="KZT", db_default="KZT")
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    # Р2: FK-less — users/hr own these rows.
    owner_id = models.IntegerField(null=True, blank=True, db_index=True)
    department_id = models.IntegerField(null=True, blank=True, db_index=True)

    created_at = models.DateTimeField(auto_now_add=True, db_default=Now(),
                                      db_index=True)
    updated_at = models.DateTimeField(auto_now=True, db_default=Now())

    def __repr__(self) -> str:  # pragma: no cover
        return f"<RequestProject id={self.id} name={self.name!r}>"


class RequestProjectMember(models.Model):
    """Who may administer / participate in a project."""

    project = models.ForeignKey(RequestProject, on_delete=models.CASCADE,
                                related_name="members")
    user_id = models.IntegerField(db_index=True)
    role = models.CharField(max_length=20, choices=ProjectMemberRole.choices,
                            default=ProjectMemberRole.MEMBER,
                            db_default=ProjectMemberRole.MEMBER)
    granted_by = models.IntegerField(null=True, blank=True)
    granted_at = models.DateTimeField(auto_now_add=True, db_default=Now())

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["project", "user_id"],
                                    name="uq_request_project_member"),
        ]


# ─────────────────────────────────────────────────────────────────────────
# Form templates
# ─────────────────────────────────────────────────────────────────────────

class RequestFormTemplate(models.Model):
    """A form template. Its schema and workflow live in immutable versions.

    ``current_version_id`` is a denormalised pointer to the latest published
    version and is deliberately NOT a ForeignKey — the original avoided the
    circular dependency between the two tables, and the same reasoning holds
    here (a template row must be insertable before any version exists).
    """

    project = models.ForeignKey(RequestProject, on_delete=models.SET_NULL,
                                null=True, blank=True,
                                related_name="templates")
    name = models.CharField(max_length=200)
    slug = models.CharField(max_length=200)
    description = models.TextField(default="", blank=True, db_default="")
    icon = models.CharField(max_length=50, default="", blank=True,
                            db_default="")
    color = models.CharField(max_length=20, default="#3b82f6",
                             db_default="#3b82f6")
    # Basic-info config from the builder's first step: group, who_can_submit,
    # submit_user_ids, show_on_workplace, prohibit_admin_manage,
    # process_admin_ids.
    config_json = models.JSONField(default=dict, blank=True, db_default={})
    is_active = models.BooleanField(default=True, db_default=True)
    status = models.CharField(max_length=16, choices=TemplateStatus.choices,
                              default=TemplateStatus.ACTIVE,
                              db_default=TemplateStatus.ACTIVE)
    created_by = models.IntegerField(null=True, blank=True)
    current_version_id = models.IntegerField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True, db_default=Now(),
                                      db_index=True)
    updated_at = models.DateTimeField(auto_now=True, db_default=Now())

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["project", "slug"],
                                    name="uq_request_form_template_slug"),
        ]

    def __repr__(self) -> str:  # pragma: no cover
        return f"<RequestFormTemplate id={self.id} slug={self.slug!r}>"


class RequestFormTemplateVersion(models.Model):
    """An immutable published snapshot of a template's schema + workflow.

    Immutability is the point: a request instance pins
    ``template_version_id`` at submit time, so editing the template later
    cannot retroactively change the form a person actually filled in or the
    route their request is travelling.
    """

    template = models.ForeignKey(RequestFormTemplate, on_delete=models.CASCADE,
                                 related_name="versions")
    version = models.IntegerField()
    schema_json = models.JSONField()
    workflow_json = models.JSONField()
    published_at = models.DateTimeField(auto_now_add=True, db_default=Now())
    published_by = models.IntegerField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["template", "version"],
                                    name="uq_request_form_template_version"),
        ]
        ordering = ["version"]


# ─────────────────────────────────────────────────────────────────────────
# Request instances
# ─────────────────────────────────────────────────────────────────────────

class RequestInstance(models.Model):
    """A submitted form travelling through its workflow."""

    code = models.CharField(max_length=64, unique=True)
    template = models.ForeignKey(RequestFormTemplate, on_delete=models.CASCADE,
                                 related_name="instances")
    # Pinned at submit time — see RequestFormTemplateVersion's docstring for
    # why this is a plain id and not a FK-with-cascade.
    template_version_id = models.IntegerField()
    project = models.ForeignKey(RequestProject, on_delete=models.SET_NULL,
                                null=True, blank=True,
                                related_name="instances")
    initiator_id = models.IntegerField(db_index=True)
    title = models.CharField(max_length=300, default="", blank=True,
                             db_default="")
    status = models.CharField(max_length=20, choices=RequestStatus.choices,
                              default=RequestStatus.DRAFT,
                              db_default=RequestStatus.DRAFT, db_index=True)
    current_node_id = models.CharField(max_length=64, null=True, blank=True,
                                       db_index=True)
    form_values_json = models.JSONField(default=dict, blank=True)
    total_amount = models.DecimalField(max_digits=18, decimal_places=2,
                                       null=True, blank=True)
    currency = models.CharField(max_length=3, null=True, blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    finalized_at = models.DateTimeField(null=True, blank=True)
    due_at = models.DateTimeField(null=True, blank=True)
    requires_admin_attention = models.BooleanField(default=False,
                                                   db_default=False)

    created_at = models.DateTimeField(auto_now_add=True, db_default=Now(),
                                      db_index=True)
    updated_at = models.DateTimeField(auto_now=True, db_default=Now())

    def __repr__(self) -> str:  # pragma: no cover
        return f"<RequestInstance id={self.id} code={self.code!r} " \
               f"status={self.status}>"


class ApprovalAction(models.Model):
    """One approver's slot on a workflow node — one row per assignee.

    A row is created when the node opens (``action`` NULL = still waiting)
    and stamped when that person acts. Keeping a row per assignee rather
    than a single "current approver" is what makes parallel approval,
    quorum rules and the audit trail all fall out of one table.
    """

    request = models.ForeignKey(RequestInstance, on_delete=models.CASCADE,
                                related_name="actions")
    node_id = models.CharField(max_length=64)
    step_index = models.IntegerField(default=0, db_default=0)
    approver_id = models.IntegerField(db_index=True)
    assigned_at = models.DateTimeField(auto_now_add=True, db_default=Now())
    action = models.CharField(max_length=20,
                              choices=ApprovalActionType.choices,
                              null=True, blank=True)
    comment = models.TextField(default="", blank=True, db_default="")
    acted_at = models.DateTimeField(null=True, blank=True)
    due_at = models.DateTimeField(null=True, blank=True)
    reminded_at = models.DateTimeField(null=True, blank=True)
    reminders_sent = models.IntegerField(default=0, db_default=0)


class RequestActivity(models.Model):
    """Append-only log of everything that happens to a request."""

    request = models.ForeignKey(RequestInstance, on_delete=models.CASCADE,
                                related_name="activity")
    actor_id = models.IntegerField(null=True, blank=True)
    event_type = models.CharField(max_length=40)
    payload = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_default=Now(),
                                      db_index=True)


class RequestWatcher(models.Model):
    """A user following a request without holding an approval role."""

    request = models.ForeignKey(RequestInstance, on_delete=models.CASCADE,
                                related_name="watchers")
    user_id = models.IntegerField(db_index=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["request", "user_id"],
                                    name="uq_request_watcher"),
        ]


class NotificationsLog(models.Model):
    """Per-recipient de-duplication of notifications this domain sends.

    ``dedup_key`` is globally unique on purpose: it is the mechanism, not a
    convenience index. A retried dispatch computes the same key and loses the
    insert, so a person cannot be pinged twice for the same event.
    """

    request = models.ForeignKey(RequestInstance, on_delete=models.CASCADE,
                                related_name="notifications")
    recipient_id = models.IntegerField(db_index=True)
    kind = models.CharField(max_length=40)
    channel = models.CharField(max_length=10, default="bot", db_default="bot")
    dedup_key = models.CharField(max_length=200, unique=True)
    created_at = models.DateTimeField(auto_now_add=True, db_default=Now(),
                                      db_index=True)


class RequestStatsDaily(models.Model):
    """Daily rollup keyed by (date, project, template).

    ``project_id``/``template_id`` are plain integers, not FKs, and ``0`` is
    used for "no project" — the original's composite PK could not hold NULL,
    and the rollup keeps that shape so a deleted project does not cascade
    away the history it contributed to.
    """

    date = models.DateField()
    project_id = models.IntegerField()
    template_id = models.IntegerField()

    created = models.IntegerField(default=0, db_default=0)
    approved = models.IntegerField(default=0, db_default=0)
    rejected = models.IntegerField(default=0, db_default=0)
    cancelled = models.IntegerField(default=0, db_default=0)
    sum_approved_amount = models.DecimalField(max_digits=18, decimal_places=2,
                                              default=0, db_default=0)
    time_to_decision_seconds_sum = models.IntegerField(default=0, db_default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["date", "project_id",
                                            "template_id"],
                                    name="uq_request_stats_daily"),
        ]


# ─────────────────────────────────────────────────────────────────────────
# Reference data (Lark-Base-style lookup tables)
# ─────────────────────────────────────────────────────────────────────────

class RequestReferenceSource(models.Model):
    """A lookup table that ``reference`` form widgets read options from.

    ``template_id`` set means this source is the auto-maintained data table
    of that template (Lark "Управление данными"); NULL means a manually
    managed source. It is a plain integer rather than a FK because the data
    table deliberately outlives a soft-deleted template.
    """

    slug = models.CharField(max_length=64, unique=True, db_index=True)
    name = models.CharField(max_length=200)
    columns_json = models.JSONField(default=list, blank=True, db_default=[])
    created_by = models.IntegerField(null=True, blank=True)
    template_id = models.IntegerField(null=True, blank=True, db_index=True)
    # Extra viewers granted by the owner, on top of the template creator and
    # the process admins.
    access_ids = models.JSONField(default=list, blank=True, db_default=[])

    created_at = models.DateTimeField(auto_now_add=True, db_default=Now(),
                                      db_index=True)
    updated_at = models.DateTimeField(auto_now=True, db_default=Now())

    @property
    def columns(self) -> list:
        return self.columns_json or []


class RequestReferenceRow(models.Model):
    """One row of a reference source."""

    source = models.ForeignKey(RequestReferenceSource,
                               on_delete=models.CASCADE, related_name="rows")
    data_json = models.JSONField(default=dict, blank=True, db_default={})
    # For a template data table: the request instance this row mirrors, so
    # the row can be upserted on every instance change. NULL for manual rows.
    instance_id = models.IntegerField(null=True, blank=True, db_index=True)

    @property
    def data(self) -> dict:
        return self.data_json or {}


# ─────────────────────────────────────────────────────────────────────────
# Audit
# ─────────────────────────────────────────────────────────────────────────

class AuditLog(models.Model):
    """Privileged-action audit trail for this domain.

    Same shape as ``apps.cms.models.AuditLog`` / ``apps.media_files``' — the
    repo keeps one per app rather than a shared table so a domain can be
    disabled, migrated or decommissioned without touching anyone else's
    history.
    """

    user_id = models.IntegerField(null=True, blank=True, db_index=True)
    action = models.CharField(max_length=100, db_index=True)
    resource_type = models.CharField(max_length=100)
    resource_id = models.CharField(max_length=100, null=True, blank=True,
                                   db_index=True)
    changes = models.JSONField(null=True, blank=True)
    ip_address = models.CharField(max_length=45, null=True, blank=True)
    user_agent = models.TextField(null=True, blank=True)
    correlation_id = models.CharField(max_length=36, null=True, blank=True,
                                      db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_default=Now(),
                                      db_index=True)
