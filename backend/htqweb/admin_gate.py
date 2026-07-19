"""Django-admin permission gate for the platform's service on/off switch.

Task 2.6 closes the hole flagged in the Phase 0 final review: ``/django-admin/``
is mounted directly in ``htqweb/urls.py`` and never passes through
``ServiceGateMiddleware`` (that middleware only matches ``/api/...`` and
``/ws/...`` prefixes — see ``htqweb/middleware/service_gate.py``). Once domain
models are registered in the admin, a disabled app's data would otherwise stay
fully readable *and* writable through the admin UI even while the API
correctly answers 503 for it. ``ServiceGatedAdminMixin`` closes that gap at
the ``ModelAdmin`` permission-hook layer, the same layer Django itself uses to
decide what shows up on the admin index and whether add/change/delete/view
requests are allowed.

Each hook below computes the normal (superclass) result and ANDs it with
``service_enabled(<service for this model's app_label>)``. Superclass-false
short-circuits before the registry is even consulted, so a user who already
lacks the base permission (e.g. a non-superuser, per decision Р1 —
``apps.users.models.User.has_perm``) pays no extra cost.

When a service is disabled:
- ``has_module_permission`` -> False -> the whole section disappears from the
  admin index (``AdminSite.index()`` filters apps by this).
- ``has_view/add/change/delete_permission`` -> False -> a direct GET to the
  changelist/change/add form is denied by Django's own admin view code, which
  produces its normal 403-or-redirect-to-login behavior (see
  ``ModelAdmin._changeform_view``/``changelist_view`` -> ``PermissionDenied``).
  That is deliberately Django-native, not a custom 503 envelope — the 503
  JSON envelope is the API gate's contract (``apps.core.services.
  disabled_payload``); the admin is a Django app and should fail the Django
  way.

``ServiceStatus`` itself (the switch) must NEVER be wrapped in this mixin —
see ``apps/core/admin.py`` for the anti-lockout reasoning.
"""

from apps.core.services import service_enabled
# APP_LABEL_TO_SERVICE lives in htqweb.middleware.service_gate, directly
# below PREFIX_TO_SERVICE — both maps describe the same service topology and
# must be updated together, so they're kept in the same file rather than
# duplicated here. Re-exported (not redefined) so existing importers of
# htqweb.admin_gate.APP_LABEL_TO_SERVICE / .service_name_for_app_label keep
# working.
from htqweb.middleware.service_gate import (  # noqa: F401
    APP_LABEL_TO_SERVICE,
    service_name_for_app_label,
)


class ServiceGatedAdminMixin:
    """Mix into a ``ModelAdmin`` to make every permission hook additionally
    require the model's owning service to be enabled in the registry.

    Do NOT mix this into ``ServiceStatusAdmin`` — see apps/core/admin.py.
    """

    def _service_enabled(self) -> bool:
        return service_enabled(service_name_for_app_label(self.opts.app_label))

    def has_module_permission(self, request) -> bool:
        return super().has_module_permission(request) and self._service_enabled()

    def has_view_permission(self, request, obj=None) -> bool:
        return super().has_view_permission(request, obj) and self._service_enabled()

    def has_add_permission(self, request) -> bool:
        return super().has_add_permission(request) and self._service_enabled()

    def has_change_permission(self, request, obj=None) -> bool:
        return super().has_change_permission(request, obj) and self._service_enabled()

    def has_delete_permission(self, request, obj=None) -> bool:
        return super().has_delete_permission(request, obj) and self._service_enabled()
