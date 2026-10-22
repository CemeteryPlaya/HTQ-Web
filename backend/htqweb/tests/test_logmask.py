"""Маскировка секретов в путях логов (htqweb/logmask.py)."""

from __future__ import annotations

import logging

from htqweb.logmask import MaskSecretPaths, mask

TOKEN = "k3J9-token_value_0123456789abcdef0123456789"


def test_portal_token_is_masked_in_api_and_page_paths():
    assert mask(f"Forbidden: /api/tender/v1/supplier/{TOKEN}/offer") == (
        "Forbidden: /api/tender/v1/supplier/***/offer")
    assert mask(f'"GET /supplier/{TOKEN} HTTP/1.1" 200') == '"GET /supplier/*** HTTP/1.1" 200'
    assert mask(f"/api/tender/v1/supplier/{TOKEN}?x=1") == "/api/tender/v1/supplier/***?x=1"


def test_other_paths_are_untouched():
    for text in ("Not Found: /api/tender/v1/tenders/12", "/api/bpp/v1/counterparties/5",
                 "supplier without slash"):
        assert mask(text) == text


def test_filter_rewrites_formatted_record_and_keeps_it():
    record = logging.LogRecord("django.request", logging.WARNING, __file__, 1, "%s: %s",
                               ("Forbidden", f"/api/tender/v1/supplier/{TOKEN}/tender"), None)
    assert MaskSecretPaths().filter(record) is True
    assert record.getMessage() == "Forbidden: /api/tender/v1/supplier/***/tender"
    assert TOKEN not in record.getMessage()
