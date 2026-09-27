"""Общее для тестов файловой подсистемы (фикстуры — в conftest.py).

Хранилище — в памяти поверх настоящего пайплайна media_files (в тестовом
прогоне нет MinIO, а ``STORAGE_BACKEND`` по умолчанию ``s3``): так
проверяются и ключ в папке владельца, и SHA-256, и политика scope, а не
заглушка на их месте.

Владельцы — пробные (``tests/testapp``): у подсистемы нет своего домена, а
её настоящие владельцы (документы модуля БЗО) ещё не написаны.
"""

from __future__ import annotations

import jwt as pyjwt
from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client

from .testapp.hooks import OWNER, UUID_OWNER  # noqa: F401 — реэкспорт для тестов

API = "/api/files/v1"
PDF = b"%PDF-1.4\n% test\n"
AUTHOR = 7
APPROVER = 11
STRANGER = 42


def token(**over) -> str:
    """Токен сотрудника без компании: пробные владельцы общие (не
    тенантные), и компания в запросе им не нужна."""
    claims = {
        "user_id": AUTHOR, "username": "u", "email": "u@htq.test",
        "is_staff": False, "is_superuser": False, "is_admin": False,
        "token_type": "access", "iat": 1, "exp": 9_999_999_999,
        "iss": "htqweb-auth", "sub": str(over.get("user_id", AUTHOR)),
        **over,
    }
    return pyjwt.encode(claims, settings.JWT_SECRET, algorithm="HS256")


def superuser_token(**over) -> str:
    return token(user_id=9, is_superuser=True, is_staff=True, is_admin=True, **over)


def auth(tok: str | None = None) -> dict:
    return {"HTTP_AUTHORIZATION": f"Bearer {tok or token()}"}


class FakeStorage:
    def __init__(self):
        self.objects: dict[str, bytes] = {}

    def save(self, path, data, content_type=None):
        self.objects[path] = data

    def open(self, path, byte_range=None):
        return self.objects[path]

    def delete(self, path):
        self.objects.pop(path, None)

    def exists(self, path):
        return path in self.objects

    def size(self, path):
        return len(self.objects[path])


def files_url(owner_id, owner_type: str = OWNER) -> str:
    return f"{API}/{owner_type}/{owner_id}/files/"


def upload(client: Client, owner_id, *, name="kp.pdf", content=PDF,
           mime="application/pdf", file_type="probe.kp", tok=None,
           key: str | None = None, owner_type: str = OWNER, **meta):
    """``meta`` — дополнительные ключи WSGI-окружения (``REMOTE_ADDR``,
    ``HTTP_USER_AGENT``…), как у ``Client.post``."""
    extra = {"HTTP_IDEMPOTENCY_KEY": key} if key else {}
    return client.post(files_url(owner_id, owner_type),
                       {"file": SimpleUploadedFile(name, content, mime),
                        "file_type": file_type},
                       **auth(tok), **extra, **meta)


def upload_version(client: Client, owner_id, document_id: str, base_file_id,
                   *, name="kp-v2.pdf", content=PDF + b"v2", mime="application/pdf",
                   tok=None, key: str | None = None, owner_type: str = OWNER):
    extra = {"HTTP_IDEMPOTENCY_KEY": key} if key else {}
    data = {"file": SimpleUploadedFile(name, content, mime)}
    if base_file_id is not None:
        data["base_file_id"] = str(base_file_id)
    return client.post(f"{files_url(owner_id, owner_type)}{document_id}/versions/",
                       data, **auth(tok), **extra)


def delete(client: Client, owner_id, document_id: str, tok=None,
           owner_type: str = OWNER):
    return client.delete(f"{files_url(owner_id, owner_type)}{document_id}/", **auth(tok))


def folder(client: Client, owner_id, tok=None, owner_type: str = OWNER) -> dict:
    resp = client.get(files_url(owner_id, owner_type), **auth(tok))
    assert resp.status_code == 200, resp.content
    return resp.json()


def assert_tz_error(resp, status: int, code: str) -> dict:
    """Ошибка в конверте D-28: {detail, code, fields, details}."""
    assert resp.status_code == status, resp.content
    body = resp.json()
    assert set(body) == {"detail", "code", "fields", "details"}, body
    assert body["code"] == code
    assert body["detail"] and "Ошибка" != body["detail"].strip()
    return body
