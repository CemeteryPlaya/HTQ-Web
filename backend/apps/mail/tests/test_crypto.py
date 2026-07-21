"""Крипто-слой домена mail — буквальный порт
services/email/app/services/crypto.py::CryptoService (AES-256-GCM).

Решение 2 брифа: htqweb/settings трогать нельзя (вне зоны apps/mail) — ключ
читается через ``getattr(django.conf.settings, "ENCRYPTION_KEY", <dev-дефолт
64 hex>)`` прямо в apps/mail/services/crypto.py. Тесты проверяют
round-trip и то, что ciphertext НЕ похож на plaintext (формат:
base64(nonce[12] + ciphertext)).
"""
import base64

import pytest

from apps.mail.services.crypto import CryptoService, crypto_service


def test_module_level_singleton_uses_dev_default_key():
    # settings.py трогать нельзя — crypto_service должен подняться на
    # dev-дефолтном ключе без внешней настройки (решение 2 брифа).
    assert crypto_service is not None


def test_encrypt_decrypt_round_trip():
    plaintext = "ya29.a0Ael9sCz-super-secret-access-token"
    encrypted = crypto_service.encrypt(plaintext)
    assert encrypted != plaintext
    assert crypto_service.decrypt(encrypted) == plaintext


def test_encrypt_output_is_base64_nonce_plus_ciphertext():
    plaintext = "refresh-token-value"
    encrypted = crypto_service.encrypt(plaintext)
    raw = base64.b64decode(encrypted)
    # nonce (12 байт) + ciphertext + 16-байтный GCM tag
    assert len(raw) >= 12 + 16
    assert len(raw) > len(plaintext.encode("utf-8"))


def test_encrypt_is_nondeterministic_random_nonce_per_call():
    plaintext = "same-plaintext-twice"
    a = crypto_service.encrypt(plaintext)
    b = crypto_service.encrypt(plaintext)
    assert a != b  # разные nonce -> разный ciphertext
    assert crypto_service.decrypt(a) == plaintext
    assert crypto_service.decrypt(b) == plaintext


def test_decrypt_rejects_tampered_ciphertext():
    encrypted = crypto_service.encrypt("do-not-tamper")
    raw = bytearray(base64.b64decode(encrypted))
    raw[-1] ^= 0xFF  # портим последний байт GCM-тега
    tampered = base64.b64encode(bytes(raw)).decode("utf-8")
    with pytest.raises(Exception):
        crypto_service.decrypt(tampered)


def test_service_rejects_short_key(settings):
    settings.ENCRYPTION_KEY = "too-short"
    with pytest.raises(ValueError):
        CryptoService()
