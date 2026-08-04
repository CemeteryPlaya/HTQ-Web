"""Card permission keys are registered and assigned to the right levels —
порт services/hr/tests/integration/test_card_permissions.py 1:1 (данные
``apps.hr.permissions`` были перенесены буквально ранее — этот тест ловит
любую случайную регрессию пресетов при будущих правках модуля)."""
from __future__ import annotations

from apps.hr.permissions import ALL_KEYS, LEVEL_PRESETS

CARD_KEYS = {
    "hr.card.financial.view", "hr.card.financial.edit",
    "hr.card.personal.view", "hr.card.personal.edit",
    "hr.card.groups.view", "hr.card.groups.edit",
}

# Секция certs (СРО/охрана труда) удалена вместе с колонками карточки —
# её ключей не должно остаться ни в каталоге, ни в одном пресете.
REMOVED_KEYS = {"hr.card.certs.view", "hr.card.certs.edit"}


def test_all_card_keys_registered():
    assert CARD_KEYS <= ALL_KEYS


def test_certs_keys_are_gone():
    assert not (REMOVED_KEYS & ALL_KEYS)
    for preset in LEVEL_PRESETS.values():
        assert not (REMOVED_KEYS & preset)


def test_middle_has_groups_only():
    assert {"hr.card.groups.view", "hr.card.groups.edit"} <= LEVEL_PRESETS["middle"]
    assert "hr.card.financial.view" not in LEVEL_PRESETS["middle"]
    assert "hr.card.personal.view" not in LEVEL_PRESETS["middle"]


def test_senior_has_all_card_keys():
    assert CARD_KEYS <= LEVEL_PRESETS["senior"]


def test_lead_has_all_card_keys():
    assert CARD_KEYS <= LEVEL_PRESETS["lead"]


def test_junior_has_no_card_keys():
    assert not (CARD_KEYS & LEVEL_PRESETS["junior"])
