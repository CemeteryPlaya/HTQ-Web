"""Публичный API аппки cms для ДРУГИХ аппок.

Единственный способ, которым сосед имеет право обращаться к cms. Прямой импорт
apps.cms.models / apps.cms.services из другой аппки запрещён и ловится
тестом apps/core/tests/test_app_isolation.py.

Каждая функция начинается с require_service("cms"): если аппка выключена,
вызывающий получит ServiceDisabled, который api_view превратит в 503-конверт
(а не в 500) — см. htqweb/http.py.
"""
from apps.core.services import require_service
from apps.cms.models import ConferenceInvite, News


def get_published_news(limit: int = 10) -> list[dict]:
    require_service("cms")
    rows = (News.objects.filter(published=True)
            .order_by("-published_at")[:limit]
            .values("id", "title", "slug", "published_at"))
    return list(rows)


def get_conference_room_title(room_id: str) -> str:
    """Название встречи, под которым комнату звали в приглашении.

    Нужно apps.conference: комнату заводит браузер случайной строкой, и в
    истории встреч «Планёрка отдела разработки» читается несравнимо лучше,
    чем `a3f9c1b2e4d6`. Само название живёт на приглашении, а приглашения —
    зона cms, поэтому сосед получает его отсюда, а не запросом к моделям.

    Берём самое свежее НЕ отозванное приглашение комнаты: у одной комнаты их
    может быть несколько (позвали ещё людей отдельной ссылкой), и последняя
    формулировка ближе к тому, чем встреча стала. Пустая строка, если
    приглашений не было вовсе — в комнату можно войти и просто по адресу.
    """
    require_service("cms")
    title = (ConferenceInvite.objects
             .filter(room_id=room_id, revoked_at__isnull=True)
             .exclude(title="")
             .order_by("-created_at")
             .values_list("title", flat=True)
             .first())
    return title or ""
