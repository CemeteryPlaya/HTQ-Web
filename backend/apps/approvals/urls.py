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
]
