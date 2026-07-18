"""Integration tests for Task APIs."""

import pytest
import pytest_asyncio
from tests.conftest import user_headers


@pytest_asyncio.fixture
async def seed_user(session):
    """Insert a user_replica row matching the user_headers() user_id (=2)."""
    from app.models.user_replica import User

    user = User(id=2, username="testuser")
    session.add(user)
    await session.commit()
    return user


@pytest.mark.asyncio
async def test_create_task(client, seed_user):
    resp = await client.post(
        "/api/tasks/v1/tasks/",
        json={
            "summary": "Implement Calendar",
            "description": "Port calendar endpoints to FastAPI",
            "task_type": "story",
            "priority": "high",
        },
        headers=user_headers(),
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["summary"] == "Implement Calendar"
    assert "TASK-" in data["key"]
    return data["id"]


@pytest.mark.asyncio
async def test_calendar_events(client, seed_user):
    # Create event
    resp = await client.post(
        "/api/tasks/v1/calendar/",
        json={
            "title": "Release planning",
            "start_date": "2026-05-01",
            "end_date": "2026-05-02",
        },
        headers=user_headers(),
    )
    assert resp.status_code == 201


@pytest.mark.asyncio
async def test_calendar_timeline_returns_tasks_and_events(client, seed_user):
    task_resp = await client.post(
        "/api/tasks/v1/tasks/",
        json={
            "summary": "Prepare roadmap",
            "task_type": "task",
            "priority": "medium",
            "start_date": "2026-05-04",
            "due_date": "2026-05-08",
        },
        headers=user_headers(),
    )
    assert task_resp.status_code == 201

    event_resp = await client.post(
        "/api/tasks/v1/calendar/",
        json={
            "title": "Sprint planning",
            "start_date": "2026-05-05",
            "end_date": "2026-05-05",
            "is_global": True,
        },
        headers=user_headers(),
    )
    assert event_resp.status_code == 201

    resp = await client.get(
        "/api/tasks/v1/calendar/timeline/?start=2026-05-01&end=2026-05-31",
        headers=user_headers(),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert [task["summary"] for task in body["tasks"]] == ["Prepare roadmap"]
    assert [event["title"] for event in body["events"]] == ["Sprint planning"]

    event_id = resp.json()["id"]

    # List events
    resp = await client.get("/api/tasks/v1/calendar/", headers=user_headers())
    assert resp.status_code == 200
    assert len(resp.json()) > 0

    # Create exception
    resp = await client.post(
        f"/api/tasks/v1/calendar/{event_id}/exceptions/",
        json={"exception_date": "2026-05-02", "is_cancelled": True},
        headers=user_headers()
    )
    assert resp.status_code == 201


@pytest.mark.asyncio
async def test_production_calendar_kazakhstan_2026_holidays(client, seed_user):
    resp = await client.get(
        "/api/tasks/v1/production-calendar/?date__gte=2026-01-01&date__lte=2026-12-31",
        headers=user_headers(),
    )
    assert resp.status_code == 200

    by_date = {item["date"]: item for item in resp.json()}
    expected_holidays = {
        "2026-01-01": "Новый год",
        "2026-01-02": "Новый год",
        "2026-01-07": "Православное Рождество",
        "2026-03-09": "Международный женский день (перенос)",
        "2026-03-21": "Наурыз мейрамы",
        "2026-03-24": "Наурыз мейрамы (перенос)",
        "2026-03-25": "Наурыз мейрамы (перенос)",
        "2026-05-01": "Праздник единства народа Казахстана",
        "2026-05-07": "День защитника Отечества",
        "2026-05-11": "День Победы (перенос)",
        "2026-05-27": "Курбан-айт",
        "2026-07-06": "День Столицы",
        "2026-08-31": "День Конституции Республики Казахстан (перенос)",
        "2026-10-26": "День Республики (перенос)",
        "2026-12-16": "День Независимости",
    }
    for day, note in expected_holidays.items():
        assert by_date[day]["day_type"] == "holiday"
        assert by_date[day]["note"] == note


@pytest.mark.asyncio
async def test_update_production_calendar_day(client, seed_user):
    resp = await client.patch(
        "/api/tasks/v1/production-calendar/2026-02-03/",
        json={"day_type": "holiday", "note": "Company day off"},
        headers=user_headers(),
    )
    assert resp.status_code == 200
    assert resp.json()["day_type"] == "holiday"
    assert resp.json()["note"] == "Company day off"

    resp = await client.get(
        "/api/tasks/v1/production-calendar/?date__gte=2026-02-01&date__lte=2026-02-07",
        headers=user_headers(),
    )
    assert resp.status_code == 200
    by_date = {item["date"]: item for item in resp.json()}
    assert by_date["2026-02-03"]["day_type"] == "holiday"
    assert by_date["2026-02-03"]["note"] == "Company day off"
