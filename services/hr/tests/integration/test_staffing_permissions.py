"""Staffing permission keys registered + senior/lead only."""

from app.auth.permissions import ALL_KEYS, LEVEL_PRESETS


def test_staffing_keys_registered():
    assert {"hr.staffing.view", "hr.staffing.manage"} <= ALL_KEYS


def test_only_senior_lead_have_staffing():
    for lvl in ("junior", "middle"):
        assert "hr.staffing.view" not in LEVEL_PRESETS[lvl]
        assert "hr.staffing.manage" not in LEVEL_PRESETS[lvl]
    for lvl in ("senior", "lead"):
        assert "hr.staffing.view" in LEVEL_PRESETS[lvl]
        assert "hr.staffing.manage" in LEVEL_PRESETS[lvl]
