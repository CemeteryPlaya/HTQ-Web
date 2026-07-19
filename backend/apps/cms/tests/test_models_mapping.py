import pytest

from apps.cms import models


def test_cms_models_own_their_schema():
    """Django владеет схемой: идиоматичные Django-модели, без FastAPI-схем."""
    for model in (models.News, models.ContactRequest, models.Category,
                  models.Tag, models.NewsAttachment, models.AuditLog):
        assert model._meta.managed is True, model.__name__


def test_news_table_uses_idiomatic_django_name():
    # public-схема, стандартное имя Django (не 'cms"."news' из FastAPI-порта).
    assert models.News._meta.db_table == 'cms_news'


@pytest.mark.django_db
def test_news_roundtrip_uses_real_column_names():
    n = models.News.objects.create(
        title="T", slug="t", excerpt="", summary="", content="",
        category="", status="draft", published=False,
    )
    n.refresh_from_db()
    assert n.slug == "t"
    assert n.status == "draft"
