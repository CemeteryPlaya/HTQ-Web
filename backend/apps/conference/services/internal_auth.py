"""Аутентификация канала SFU → Django (``/api/conference/v1/internal/*``).

Почему не JWT, которым платформа пользуется везде. У SFU нет пользователя:
он сообщает не «я, Иванов, прошу», а «в комнате X начался звонок». Выписывать
ему сервисный токен пришлось бы, расширив ``api_view`` новым режимом
авторизации и ``TokenPayload`` — полем без ``user_id``, чего эта модель
намеренно не допускает (см. htqweb/authn/payload.py). Общий секрет решает ту
же задачу без правки контракта аутентификации всей платформы.

Секрет обязателен: пустой ``CONFERENCE_INTERNAL_TOKEN`` закрывает эндпоинты
наглухо, а не открывает их всем. Иначе забытая переменная окружения молча
превратила бы приём фактов о встречах в анонимную ручку записи в БД.
"""

from __future__ import annotations

import hmac

from django.conf import settings
from django.core.exceptions import PermissionDenied

#: Заголовок, которым SFU предъявляет секрет. Не Authorization — чтобы его
#: нельзя было спутать с пользовательским Bearer-токеном ни в коде, ни в логах.
HEADER = "X-HTQ-Internal-Token"


def require_internal(request) -> None:
    """Пропустить запрос от SFU/рекордера или бросить 403.

    ``PermissionDenied`` ``api_view`` превращает в ``{"detail": "Forbidden"}``
    с кодом 403 — тот же конверт, что у остальной платформы.
    """
    expected = (settings.CONFERENCE_INTERNAL_TOKEN or "").strip()
    if not expected:
        raise PermissionDenied("internal channel is not configured")

    presented = (request.headers.get(HEADER) or "").strip()
    # compare_digest, а не ==: сравнение секретов на равенство утекает их
    # длину и первый несовпавший байт через время ответа.
    #
    # Сравниваем БАЙТЫ, а не строки: строковая форма compare_digest требует
    # ASCII и бросает TypeError на чём угодно другом. То есть заголовок с
    # кириллицей — который кто угодно может прислать снаружи — превращал бы
    # честный отказ 403 в необработанные 500.
    if not presented or not hmac.compare_digest(presented.encode("utf-8"),
                                                expected.encode("utf-8")):
        raise PermissionDenied("bad internal token")
