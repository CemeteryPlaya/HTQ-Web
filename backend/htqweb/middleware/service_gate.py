from django.http import JsonResponse

from apps.core.services import disabled_payload, service_status

# Префикс URL → имя сервиса в реестре. Единственное место маппинга.
PREFIX_TO_SERVICE = {
    "/api/users/": "users",
    "/api/hr/": "hr",
    "/api/tasks/": "tasks",
    "/api/requests/": "approvals",
    "/api/cms/": "cms",
    "/api/media/": "media",
    "/api/email/": "mail",
    "/api/messenger/": "messenger",
    "/api/contracts/": "contracts",
    "/api/signoff/": "signoff",
    "/api/access/": "access",
    "/ws/messenger/": "messenger",
    "/ws/sfu/": "conference",
}

# Django app_label -> service-registry name (the name apps.core.services.
# service_enabled()/ServiceStatus.app_label expect), for the handful of apps
# whose Django app_label doesn't match the registry's service name 1:1.
#
# Kept directly below PREFIX_TO_SERVICE on purpose: both maps describe the
# same service topology and must be updated together — a reader/editor of
# one has no excuse for missing the other. (htqweb.admin_gate imports this
# from here rather than defining its own copy, for the same reason.)
#
# Known divergences, per PREFIX_TO_SERVICE's prefix -> service mapping:
#   "/api/requests/" -> service "approvals"
#   "/api/email/"    -> service "mail"
#   "/api/media/"    -> service "media"
# Whatever exact app_label those not-yet-ported apps land on, register it
# here so ServiceGatedAdminMixin asks the registry about the right name.
# Anything absent from this map falls back to using the app_label itself as
# the service name — true today for apps.core/apps.users/apps.cms, whose
# app_labels (core/users/cms) already match their KNOWN_SERVICES entry.
APP_LABEL_TO_SERVICE = {
    "approvals": "approvals",
    "mail": "mail",
    "media_files": "media",
}


def service_name_for_app_label(app_label: str) -> str:
    return APP_LABEL_TO_SERVICE.get(app_label, app_label)


class ServiceGateMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        for prefix, name in PREFIX_TO_SERVICE.items():
            if request.path.startswith(prefix):
                enabled, message = service_status(name)
                if not enabled:
                    return JsonResponse(disabled_payload(name, message), status=503)
                break
        return self.get_response(request)
