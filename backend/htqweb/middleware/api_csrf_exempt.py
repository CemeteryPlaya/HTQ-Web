"""CSRF-exempt для всего /api/.

Весь API платформы stateless на JWT (заголовок Authorization), а не на
session-cookie, поэтому CSRF к нему неприменим — ``htqweb.http.api_view`` и так
помечает обработчики ``@csrf_exempt``. Но метод-диспетчеры (тонкие функции,
раскидывающие POST/GET/... по декорированным обработчикам, напр.
``apps.hr.views.departments_collection``) — обычные вью без ``csrf_exempt``, и
``CsrfViewMiddleware`` отклонял бы POST/PUT/PATCH/DELETE к ним 403-CSRF в
РЕАЛЬНОМ запросе (Django test Client отключает CSRF-проверки, поэтому в тестах
это не проявлялось — только на живом фронте/curl).

Ставим ``request._dont_enforce_csrf_checks = True`` для путей ``/api/`` в
middleware ПЕРЕД ``CsrfViewMiddleware`` — тот уважает этот флаг (тот же
механизм, что использует test Client). ``django-admin`` (session + HTML-формы)
живёт под ``/django-admin/`` и свою CSRF-защиту сохраняет.
"""


class ApiCsrfExemptMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path.startswith("/api/"):
            request._dont_enforce_csrf_checks = True
        return self.get_response(request)
