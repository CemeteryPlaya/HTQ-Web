"""Calendar permission keys registered + assigned to levels."""

from app.auth.permissions import ALL_KEYS, LEVEL_PRESETS


def test_calendar_keys_registered():
    assert {"hr.calendar.view", "hr.calendar.manage"} <= ALL_KEYS


def test_all_levels_can_view():
    for lvl in ("junior", "middle", "senior", "lead"):
        assert "hr.calendar.view" in LEVEL_PRESETS[lvl]


def test_only_senior_lead_manage():
    assert "hr.calendar.manage" not in LEVEL_PRESETS["junior"]
    assert "hr.calendar.manage" not in LEVEL_PRESETS["middle"]
    assert "hr.calendar.manage" in LEVEL_PRESETS["senior"]
    assert "hr.calendar.manage" in LEVEL_PRESETS["lead"]
