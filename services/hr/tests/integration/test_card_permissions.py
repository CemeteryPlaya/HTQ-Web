"""Card permission keys are registered and assigned to the right levels."""

from app.auth.permissions import ALL_KEYS, LEVEL_PRESETS

CARD_KEYS = {
    "hr.card.financial.view", "hr.card.financial.edit",
    "hr.card.personal.view", "hr.card.personal.edit",
    "hr.card.certs.view", "hr.card.certs.edit",
    "hr.card.groups.view", "hr.card.groups.edit",
}


def test_all_card_keys_registered():
    assert CARD_KEYS <= ALL_KEYS


def test_middle_has_certs_and_groups_only():
    assert {"hr.card.certs.view", "hr.card.certs.edit",
            "hr.card.groups.view", "hr.card.groups.edit"} <= LEVEL_PRESETS["middle"]
    assert "hr.card.financial.view" not in LEVEL_PRESETS["middle"]
    assert "hr.card.personal.view" not in LEVEL_PRESETS["middle"]


def test_senior_has_all_card_keys():
    assert CARD_KEYS <= LEVEL_PRESETS["senior"]


def test_lead_has_all_card_keys():
    assert CARD_KEYS <= LEVEL_PRESETS["lead"]


def test_junior_has_no_card_keys():
    assert not (CARD_KEYS & LEVEL_PRESETS["junior"])
