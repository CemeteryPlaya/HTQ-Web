"""Публичный API аппки cms для ДРУГИХ аппок.

Единственный способ, которым сосед имеет право обращаться к cms. Прямой импорт
apps.cms.models / apps.cms.services из другой аппки запрещён и ловится
тестом apps/core/tests/test_app_isolation.py.

Каждая функция начинается с require_service("cms"): если аппка выключена,
вызывающий получит ServiceDisabled, который api_view превратит в 503-конверт
(а не в 500) — см. htqweb/http.py.
"""
from apps.core.services import require_service


def get_published_news(limit: int = 10) -> list[dict]:
    require_service("cms")
    from apps.cms.models import News
    rows = (News.objects.filter(published=True)
            .order_by("-published_at")[:limit]
            .values("id", "title", "slug", "published_at"))
    return list(rows)
