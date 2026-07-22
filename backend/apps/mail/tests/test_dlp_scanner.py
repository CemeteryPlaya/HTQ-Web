"""Контракт DLP-сканера — буквальный порт
``services/email/tests/integration/test_email_api.py::test_dlp_scanner``
(плюс edge-cases не покрытые исходным тестом)."""
from apps.mail.services.dlp_scanner import dlp_scanner


def test_flags_ssn_pattern():
    assert dlp_scanner.scan("Here is my ssn: 123-45-6789") is True


def test_allows_normal_text():
    assert dlp_scanner.scan("Just a normal email.") is False


def test_flags_credit_card_pattern():
    assert dlp_scanner.scan("card: 4111 1111 1111 1111") is True


def test_flags_api_key_pattern():
    assert dlp_scanner.scan("sk-" + "a" * 32) is True


def test_empty_content_is_safe():
    assert dlp_scanner.scan("") is False
    assert dlp_scanner.scan(None) is False
