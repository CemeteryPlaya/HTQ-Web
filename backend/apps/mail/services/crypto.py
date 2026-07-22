"""AES-256-GCM шифрование OAuth-токенов — буквальный порт
``services/email/app/services/crypto.py::CryptoService``.

Формат неизменен: ``base64(nonce[12 байт] + ciphertext)``. Токены в БД
(``OAuthToken.encrypted_access_token``/``encrypted_refresh_token``) хранятся
ТОЛЬКО в этом виде; расшифровка происходит лениво, в момент фактического
использования (revoke при disconnect, будущий IMAP/SMTP-клиент).

Решение 2 (бриф mail-core): ``htqweb/settings`` трогать нельзя — это ЧУЖАЯ
зона (вне ``backend/apps/mail/**``). Ключ читается через
``getattr(django.conf.settings, "ENCRYPTION_KEY", _DEV_DEFAULT_KEY)`` ПРЯМО
здесь, а не как объявленный атрибут settings-модуля:
  * если оператор задаст ``ENCRYPTION_KEY`` в env/settings (любой Django-
    settings-модуль принимает произвольные атрибуты, объявленные они там или
    нет) — используется он;
  * иначе используется ``_DEV_DEFAULT_KEY`` — ТОТ ЖЕ placeholder-дефолт, что
    ``services/email/app/core/settings.py::Settings.encryption_key`` (не
    секрет, не для прода): dev-окружение и тестовая сюита поднимаются без
    внешней настройки.
Прод обязан задать реальный ``ENCRYPTION_KEY`` явным env — иначе все
инстансы платформы, включая dev, шифруют одним и тем же публично известным
ключом (это ЖЕ верно и для FastAPI-исходника, у которого дефолт точно такой
же — не новый риск, а перенесённый как есть).
"""
from __future__ import annotations

import base64
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from django.conf import settings

# Идентичен services/email/app/core/settings.py::Settings.encryption_key.
_DEV_DEFAULT_KEY = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"


class CryptoService:
    def __init__(self) -> None:
        key_hex = getattr(settings, "ENCRYPTION_KEY", _DEV_DEFAULT_KEY)
        if len(key_hex) != 64:
            raise ValueError("ENCRYPTION_KEY must be exactly 64 hex characters (32 bytes).")
        self.key = bytes.fromhex(key_hex)
        self.aesgcm = AESGCM(self.key)

    def encrypt(self, data: str) -> str:
        """Encrypt string, returning base64 encoded nonce+ciphertext."""
        nonce = os.urandom(12)  # 96-bit nonce for GCM
        ciphertext = self.aesgcm.encrypt(nonce, data.encode("utf-8"), None)
        return base64.b64encode(nonce + ciphertext).decode("utf-8")

    def decrypt(self, encrypted_data: str) -> str:
        """Decrypt base64 encoded nonce+ciphertext."""
        raw_data = base64.b64decode(encrypted_data)
        nonce = raw_data[:12]
        ciphertext = raw_data[12:]
        decrypted = self.aesgcm.decrypt(nonce, ciphertext, None)
        return decrypted.decode("utf-8")


crypto_service = CryptoService()
