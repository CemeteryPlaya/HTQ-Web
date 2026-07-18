"""Groups service: graceful empty when Mongo absent; replace is a no-op then."""

import pytest

from app.services.employee_groups_service import EmployeeGroupsService

pytestmark = pytest.mark.asyncio


async def test_read_returns_empty_when_mongo_absent(monkeypatch):
    import app.services.employee_groups_service as mod
    monkeypatch.setattr(mod, "get_hr_groups_collection", lambda: None)
    svc = EmployeeGroupsService()
    groups = await svc.read(123)
    assert groups == {"education": [], "experience": [], "relatives": []}


async def test_replace_noop_when_mongo_absent(monkeypatch):
    import app.services.employee_groups_service as mod
    monkeypatch.setattr(mod, "get_hr_groups_collection", lambda: None)
    svc = EmployeeGroupsService()
    out = await svc.replace(123, {"education": [{"institution": "X"}]})
    assert out["education"] == []
