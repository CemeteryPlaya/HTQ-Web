"""Crypto utilities for encrypting/decrypting OAuth tokens (AES-256-GCM)."""

import base64
import os
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from app.core.settings import settings


class CryptoService:
    def __init__(self):
        # Ensure key is 32 bytes for AES-256
        key_hex = settings.encryption_key
        if len(key_hex) != 64:
            raise ValueError("ENCRYPTION_KEY must be exactly 64 hex characters (32 bytes).")
        self.key = bytes.fromhex(key_hex)
        self.aesgcm = AESGCM(self.key)

    def encrypt(self, data: str) -> str:
        """Encrypt string, returning base64 encoded nonce+ciphertext."""
        nonce = os.urandom(12) # 96-bit nonce for GCM
        ciphertext = self.aesgcm.encrypt(nonce, data.encode('utf-8'), None)
        return base64.b64encode(nonce + ciphertext).decode('utf-8')

    def decrypt(self, encrypted_data: str) -> str:
        """Decrypt base64 encoded nonce+ciphertext."""
        raw_data = base64.b64decode(encrypted_data)
        nonce = raw_data[:12]
        ciphertext = raw_data[12:]
        decrypted = self.aesgcm.decrypt(nonce, ciphertext, None)
        return decrypted.decode('utf-8')

crypto_service = CryptoService()
