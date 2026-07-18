from django.http import JsonResponse

from apps.core.services import _status

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
    "/ws/messenger/": "messenger",
    "/ws/sfu/": "conference",
}


class ServiceGateMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        for prefix, name in PREFIX_TO_SERVICE.items():
            if request.path.startswith(prefix):
                enabled, message = _status(name)
                if not enabled:
                    return JsonResponse(
                        {"detail": message or "Сервис в данный момент недоступен",
                         "code": "service_disabled", "service": name},
                        status=503)
                break
        return self.get_response(request)
