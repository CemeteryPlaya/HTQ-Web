import pytest

from apps.cms.interface import get_published_news
from apps.core.models import ServiceStatus
from apps.core.services import ServiceDisabled


@pytest.mark.django_db
def test_interface_refuses_when_cms_disabled():
    ServiceStatus.objects.update_or_create(app_label="cms", defaults={"enabled": False})
    with pytest.raises(ServiceDisabled):
        get_published_news()


@pytest.mark.django_db
def test_get_published_news_returns_plain_dicts_of_published_only():
    from apps.cms.models import News

    News.objects.create(
        title="Draft", slug="draft", excerpt="", summary="", content="",
        category="", status="draft", published=False,
    )
    published = News.objects.create(
        title="Published", slug="published", excerpt="", summary="", content="",
        category="", status="published", published=True,
    )
    published.published_at = published.created_at
    published.save(update_fields=["published_at"])

    rows = get_published_news()

    assert rows == [{
        "id": published.id,
        "title": "Published",
        "slug": "published",
        "published_at": published.published_at,
    }]
    assert not isinstance(rows[0], News)
