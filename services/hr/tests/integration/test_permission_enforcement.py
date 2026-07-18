"""Permission presets + HRAccess.has enforcement."""

import pytest

from app.auth.permissions import LEVEL_PRESETS, expand_level

pytestmark = pytest.mark.asyncio


def test_presets_are_nested_supersets():
    assert LEVEL_PRESETS["junior"] <= LEVEL_PRESETS["middle"]
    assert LEVEL_PRESETS["middle"] <= LEVEL_PRESETS["senior"]
    assert LEVEL_PRESETS["senior"] <= LEVEL_PRESETS["lead"]


def test_senior_has_view_all_and_create_lead_has_delete():
    assert "hr.employees.view.all" in LEVEL_PRESETS["senior"]
    assert "hr.employees.create" in LEVEL_PRESETS["senior"]
    assert "hr.employees.delete" not in LEVEL_PRESETS["senior"]
    assert "hr.employees.delete" in LEVEL_PRESETS["lead"]


def test_expand_level_unknown_returns_empty():
    assert expand_level(None) == frozenset()
    assert expand_level("nope") == frozenset()
    assert expand_level("lead") == LEVEL_PRESETS["lead"]


from app.auth.hr_access import HRAccess
from app.auth.permissions import LEVEL_PRESETS


def _access(level):
    return HRAccess(level=level, permissions=LEVEL_PRESETS.get(level, frozenset()))


def test_has_checks_membership():
    a = _access("senior")
    assert a.has("hr.employees.create") is True
    assert a.has("hr.employees.delete") is False


def test_wildcard_admin_has_everything():
    a = HRAccess(level="lead", permissions=frozenset({"*"}))
    assert a.has("anything.at.all") is True


def test_wrappers_match_preset_matrix():
    expectations = {
        "junior": dict(can_read_all=False, can_write_basic=False, can_create_employee=False,
                       can_transfer_employee=False, can_delete_employee=False,
                       can_list_user_options=False, can_manage_user_options=False),
        "middle": dict(can_read_all=False, can_write_basic=True, can_create_employee=False,
                       can_transfer_employee=False, can_delete_employee=False,
                       can_list_user_options=False, can_manage_user_options=False),
        "senior": dict(can_read_all=True, can_write_basic=True, can_create_employee=True,
                       can_transfer_employee=True, can_delete_employee=False,
                       can_list_user_options=True, can_manage_user_options=False),
        "lead": dict(can_read_all=True, can_write_basic=True, can_create_employee=True,
                     can_transfer_employee=True, can_delete_employee=True,
                     can_list_user_options=True, can_manage_user_options=True),
    }
    for level, exp in expectations.items():
        a = _access(level)
        for prop, want in exp.items():
            assert getattr(a, prop) is want, f"{level}.{prop} expected {want}"
