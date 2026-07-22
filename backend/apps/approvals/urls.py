"""Route table for ``/api/requests/v1/`` (mounted by URL autodiscovery — see
``ApprovalsConfig.API_PREFIX`` and ``htqweb/urls.py``).

``APPEND_SLASH=False``, so every spelling a client uses must be registered
(PLAN.md §3). The originals declared these with trailing slashes, except
``/instances/batch-approve``; both spellings are registered throughout so a
stray slash never becomes a 404, nor a 307 that drops the auth header.

Note the mount prefix is ``api/requests/v1/`` while the app label is
``approvals``. That mismatch is deliberate and already registered in
``htqweb.middleware.service_gate`` (``PREFIX_TO_SERVICE`` +
``APP_LABEL_TO_SERVICE``, PLAN.md §4.1), so the gate resolves this prefix to
the ``approvals`` switch without any edit here.
"""

from django.urls import path

from . import views

urlpatterns = [
    # Instances. ``batch-approve`` is registered BEFORE the
    # ``<int:instance_id>`` routes so a later converter change can never let
    # the id pattern swallow it.
    path("instances/", views.instances_collection),
    path("instances/batch-approve", views.batch_approve),
    path("instances/batch-approve/", views.batch_approve),
    path("instances/<int:instance_id>", views.instance_detail),
    path("instances/<int:instance_id>/", views.instance_detail),
    path("instances/<int:instance_id>/submit/", views.submit_instance),
    path("instances/<int:instance_id>/resubmit/", views.resubmit_instance),
    path("instances/<int:instance_id>/approve/", views.approve),
    path("instances/<int:instance_id>/reject/", views.reject),
    path("instances/<int:instance_id>/request-changes/", views.request_changes),
    path("instances/<int:instance_id>/cancel/", views.cancel),
    path("instances/<int:instance_id>/recall/", views.recall),

    # SSE. The frontend's EventSource hits ``stream?token=…`` with no
    # trailing slash; the slashed alias is registered per this repo's
    # convention (APPEND_SLASH=False never redirects on its own).
    path("stream", views.stream),
    path("stream/", views.stream),

    # Projects and membership.
    path("projects/", views.projects_collection),
    path("projects/<int:project_id>", views.project_detail),
    path("projects/<int:project_id>/", views.project_detail),
    path("projects/<int:project_id>/members/", views.project_members),
    path("projects/<int:project_id>/members/<int:user_id>/",
         views.remove_member),

    # Form templates. ``templates/preview`` is registered BEFORE the
    # ``<int:template_id>`` routes for the same reason ``batch-approve`` is
    # (see module docstring) even though the int converter would not match
    # the literal "preview" anyway -- consistency with that convention.
    path("templates/preview", views.preview_template),
    path("templates/preview/", views.preview_template),
    path("templates/", views.templates_collection),
    path("templates/<int:template_id>", views.template_detail),
    path("templates/<int:template_id>/", views.template_detail),
    path("templates/<int:template_id>/deactivate/", views.deactivate_template),
    path("templates/<int:template_id>/activate/", views.activate_template),
    path("templates/<int:template_id>/versions/", views.publish_version),
    path("templates/<int:template_id>/versions/<int:version_id>",
         views.get_version),
    path("templates/<int:template_id>/versions/<int:version_id>/",
         views.get_version),

    # Statistics. Registered without a trailing slash first (the frontend's
    # own client calls these bare, per the FastAPI original's router), plus
    # the slashed alias per this repo's "register both spellings" rule.
    path("stats/overview", views.stats_overview),
    path("stats/overview/", views.stats_overview),
    path("stats/by-project", views.stats_by_project),
    path("stats/by-project/", views.stats_by_project),
    path("stats/by-template", views.stats_by_template),
    path("stats/by-template/", views.stats_by_template),
    path("stats/by-actor", views.stats_by_actor),
    path("stats/by-actor/", views.stats_by_actor),
    path("stats/heatmap", views.stats_heatmap),
    path("stats/heatmap/", views.stats_heatmap),

    # Reference data sources (Lark-Base-style lookup tables). ``my-data-
    # tables`` and ``by-slug/...`` are literal paths registered BEFORE
    # ``<int:source_id>`` for the same reason ``batch-approve`` is (see the
    # instances comment above), even though the int converter cannot match
    # them anyway.
    path("reference-sources/my-data-tables", views.my_data_tables),
    path("reference-sources/my-data-tables/", views.my_data_tables),
    path("reference-sources/by-slug/<str:slug>/options",
         views.reference_options),
    path("reference-sources/by-slug/<str:slug>/options/",
         views.reference_options),
    path("reference-sources/", views.sources_collection),
    path("reference-sources/<int:source_id>", views.source_detail),
    path("reference-sources/<int:source_id>/", views.source_detail),
    path("reference-sources/<int:source_id>/access",
         views.set_data_table_access),
    path("reference-sources/<int:source_id>/access/",
         views.set_data_table_access),
    path("reference-sources/<int:source_id>/rows/", views.rows_collection),
    path("reference-sources/<int:source_id>/rows/<int:row_id>",
         views.delete_row),
    path("reference-sources/<int:source_id>/rows/<int:row_id>/",
         views.delete_row),
]
