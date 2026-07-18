"""Unit test for the news_scheduled_publish scheduler query logic."""

import pytest
import pytest_asyncio
from datetime import datetime, timezone, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.news import News


@pytest_asyncio.fixture
async def seed_news(session: AsyncSession):
    """Seed news with various published/scheduled states."""
    now = datetime.now(timezone.utc)

    items = [
        News(
            title="Already published",
            slug="already-published",
            published=True,
            published_at=now - timedelta(hours=1),
        ),
        News(
            title="Scheduled past",
            slug="scheduled-past",
            published=False,
            published_at=now - timedelta(minutes=5),
        ),
        News(
            title="Scheduled future",
            slug="scheduled-future",
            published=False,
            published_at=now + timedelta(hours=1),
        ),
        News(
            title="Draft no date",
            slug="draft-no-date",
            published=False,
            published_at=None,
        ),
    ]
    session.add_all(items)
    await session.flush()
    return items


@pytest.mark.asyncio
async def test_scheduled_publish_query(session: AsyncSession, seed_news):
    """Verify that only unpublished news with past published_at is caught."""
    from sqlalchemy import func, update

    stmt = (
        update(News)
        .where(
            News.published.is_(False),
            News.published_at.isnot(None),
            News.published_at <= func.now(),
        )
        .values(published=True)
        .execution_options(synchronize_session=False)
    )
    result = await session.execute(stmt)

    assert result.rowcount == 1

    await session.flush()
    session.expire_all()

    all_news = (await session.execute(select(News))).scalars().all()
    by_slug = {n.slug: n for n in all_news}

    assert by_slug["already-published"].published is True
    assert by_slug["scheduled-past"].published is True
    assert by_slug["scheduled-future"].published is False
    assert by_slug["draft-no-date"].published is False
