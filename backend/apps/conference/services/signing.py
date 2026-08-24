"""Подписанные ссылки на запись встречи.

Зачем это нужно. Тег ``<video src="...">`` не отправляет заголовок
``Authorization`` — браузер о нашем JWT ничего не знает. Значит, эндпоинт
воспроизведения не может быть защищён обычной проверкой токена: плеер до
него просто не достучится.

Платформа решает это ровно одним способом, и мы им же (STRUCTURE.md §7.1):
API, у которого JWT ЕСТЬ, проверяет права и выдаёт ссылку с подписью
``?sig=&exp=``; эндпоинт по ссылке проверяет подпись вместо токена и
редиректит на свежий presigned-адрес хранилища. Права проверены один раз, в
момент выдачи, а подпись живёт недолго и привязана к конкретному объекту:
подпись, выписанная на запись одной встречи, не подойдёт к другой.

Секрет и алгоритм — общие с ``htqweb.storage.signed_url`` (там же
объяснено, почему схему нельзя менять в одиночку).
"""

from __future__ import annotations

from htqweb.storage.signed_url import signed_query, verify

#: Пространство имён в подписи. Без него ``42`` было бы неоднозначно — id
#: встречи, файла или новости, — и подпись, выданную на одно, можно было бы
#: предъявить другому.
RECORDING = "conference-recording"
POSTER = "conference-poster"


def _resource_id(kind: str, session_id: int) -> str:
    return f"{kind}:{session_id}"


def recording_url(session_id: int, *, download: bool = False) -> str:
    """Готовая к вставке в ``<video src>`` ссылка на запись."""
    query = signed_query(_resource_id(RECORDING, session_id))
    suffix = "&download=1" if download else ""
    return f"/api/conference/v1/sessions/{session_id}/recording?{query}{suffix}"


def poster_url(session_id: int) -> str:
    query = signed_query(_resource_id(POSTER, session_id))
    return f"/api/conference/v1/sessions/{session_id}/poster?{query}"


def signature_ok(kind: str, session_id: int, request) -> bool:
    """Верна ли подпись в query-параметрах запроса."""
    sig = request.GET.get("sig") or ""
    raw_exp = request.GET.get("exp") or ""
    if not sig or not raw_exp:
        return False
    try:
        exp = int(raw_exp)
    except (TypeError, ValueError):
        return False
    return verify(_resource_id(kind, session_id), sig, exp)
