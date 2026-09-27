"""Idempotency-Key для записывающих ручек (ТЗ §13.4, AC-013, D-29).

Клиент кладёт в заголовок ``Idempotency-Key`` случайный ключ на одно
действие пользователя («Отправить», «Оплатить»). Повтор с тем же ключом —
двойной клик, повтор после таймаута — получает ПЕРВЫЙ ответ, а не второй
эффект. Ключ живёт 24 часа в кэше (Redis на стенде и в проде).

Ключ кэша включает компанию, пользователя, метод и путь: один и тот же
ключ, пришедший на другую ручку или от другого человека, — другой запрос.

Одновременный повтор (первый ещё выполняется) получает 409 «уже
выполняется»: ждать первого внутри запроса значило бы держать воркер
gunicorn, а отдать 200 без тела — соврать.

Запоминается только успешный ответ (< 500): упавший запрос можно повторить
тем же ключом.
"""

from __future__ import annotations

import json

from django.core.cache import cache
from django.http import JsonResponse

from htqweb.errors import DomainError

TTL = 24 * 60 * 60
# Замок живёт с запасом дольше самого долгого запроса (gunicorn --timeout 60
# в docker-compose*.yml): снятый раньше времени замок пустил бы повтор
# выполняться параллельно с первым. Убитый воркер замок не снимет — он
# истечёт сам.
LOCK_TTL = 5 * 60
HEADER = "Idempotency-Key"


def _base(request, key: str) -> str:
    company = getattr(request, "company", None) or {}
    token = getattr(request, "token", None)
    user_id = getattr(token, "user_id", None)
    return f"idem:{company.get('slug', '-')}:{user_id}:{request.method}:{request.path}:{key}"


def lock_key(request, key: str) -> str:
    return _base(request, key) + ":lock"


def key_of(request) -> str | None:
    value = (request.headers.get(HEADER) or "").strip()
    return value[:200] or None


def replay(request, key: str) -> JsonResponse | None:
    """Сохранённый ответ на этот ключ или ``None``."""
    stored = cache.get(_base(request, key))
    if stored is None:
        return None
    response = JsonResponse(stored["body"], status=stored["status"], safe=False)
    response["Idempotent-Replay"] = "true"
    return response


def acquire(request, key: str) -> None:
    """Занять ключ на время выполнения; занят — ``DomainError`` 409."""
    if not cache.add(lock_key(request, key), 1, LOCK_TTL):
        raise DomainError(
            "E-IDEM-01",
            "Этот запрос уже выполняется. Дождитесь результата и обновите страницу.",
            status=409,
        )


def remember(request, key: str, response) -> None:
    if response.status_code >= 500 or not isinstance(response, JsonResponse):
        return
    body = json.loads(response.content or b"null")
    cache.set(_base(request, key), {"status": response.status_code, "body": body}, TTL)


def release(request, key: str) -> None:
    cache.delete(lock_key(request, key))
