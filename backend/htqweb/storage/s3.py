"""Object storage abstraction (S3/MinIO) — shared across all Django apps.

Ported from ``services/cms/app/services/s3_storage.py``. The original is
**async** (``await get_storage().save(...)``) because it ran under FastAPI/
uvicorn as one of several independently-deployed services; this monolith is
WSGI-first with synchronous views (decision Д11), so this port drops
``async``/``await`` throughout: ``boto3`` (sync) replaces ``aioboto3``,
builtin ``open()``/``pathlib``/``os`` replace ``aiofiles``. The public shape
(class names, method names/signatures, constructor kwargs, the local-vs-s3
selection in ``get_storage()``) is otherwise unchanged so ported call sites
read the same, just without the ``await``.

``get_storage()`` is deliberately NOT ``@lru_cache``d (unlike the original).
There, ``settings`` was a singleton loaded once at process start. Here,
``django.conf.settings`` can be swapped mid-process via
``django.test.override_settings`` in tests, and caching would leak a stale
backend/config across tests. Construction is cheap (no live network
handshake happens until a method is called — same as the original, which
also only opened an S3 client lazily inside each method).

Layout under the cms bucket (``htqweb-cms``) is unchanged from the FastAPI
service::

    news/<news_id>/content.md             (markdown snapshot of body)
    news/<news_id>/metadata.json          (full post fields snapshot)
    news/<news_id>/cover.<ext>            (cover image binary)
    news/<news_id>/attachments/<id>_<filename>
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Protocol, runtime_checkable

from django.conf import settings


@runtime_checkable
class Storage(Protocol):
    def save(self, path: str, data: bytes, content_type: str | None = None) -> None: ...
    def open(self, path: str, byte_range: tuple[int, int] | None = None) -> bytes: ...
    def delete(self, path: str) -> None: ...
    def exists(self, path: str) -> bool: ...
    def size(self, path: str) -> int: ...
    def presigned_get_url(self, path: str, ttl: int | None = None, *,
                          download_as: str | None = None) -> str: ...


class LocalStorage:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _resolve(self, path: str) -> Path:
        resolved = (self.base_dir / path).resolve()
        if not str(resolved).startswith(str(self.base_dir.resolve())):
            raise ValueError(f"Path traversal detected: {path}")
        return resolved

    def save(self, path: str, data: bytes, content_type: str | None = None) -> None:
        target = self._resolve(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

    def open(self, path: str, byte_range: tuple[int, int] | None = None) -> bytes:
        target = self._resolve(path)
        if not target.exists():
            raise FileNotFoundError(path)
        if byte_range is not None:
            start, end = byte_range
            length = end - start + 1
            with target.open("rb") as f:
                f.seek(start)
                return f.read(length)
        return target.read_bytes()

    def delete(self, path: str) -> None:
        target = self._resolve(path)
        if target.exists():
            os.remove(target)

    def exists(self, path: str) -> bool:
        return self._resolve(path).exists()

    def size(self, path: str) -> int:
        return self._resolve(path).stat().st_size

    def presigned_get_url(self, path: str, ttl: int | None = None, *,
                          download_as: str | None = None) -> str:
        # download_as управляет заголовком ответа S3; у file:// заголовков
        # нет, поэтому локальный бэкенд его молча игнорирует — как и bucket
        # в get_storage() (см. её докстринг): local — dev-заглушка.
        return f"file://{self._resolve(path)}"


class S3Storage:
    """S3-compatible object storage (MinIO in dev, AWS in prod)."""

    def __init__(
        self,
        bucket: str,
        endpoint: str = "",
        access_key: str = "",
        secret_key: str = "",
        region: str = "us-east-1",
        use_path_style: bool = True,
        public_endpoint: str = "",
        default_presigned_ttl: int = 3600,
    ) -> None:
        self.bucket = bucket
        self.endpoint = endpoint
        self.access_key = access_key
        self.secret_key = secret_key
        self.region = region
        self.use_path_style = use_path_style
        self.public_endpoint = public_endpoint or endpoint
        self.default_presigned_ttl = default_presigned_ttl

    def _client_config(self):
        from botocore.config import Config

        return Config(
            signature_version="s3v4",
            s3={"addressing_style": "path" if self.use_path_style else "virtual"},
        )

    def _client_kwargs(self, *, endpoint_override: str | None = None) -> dict:
        kwargs: dict = {
            "region_name": self.region,
            "config": self._client_config(),
        }
        endpoint = endpoint_override if endpoint_override is not None else self.endpoint
        if endpoint:
            kwargs["endpoint_url"] = endpoint
        if self.access_key:
            kwargs["aws_access_key_id"] = self.access_key
            kwargs["aws_secret_access_key"] = self.secret_key
        return kwargs

    def _client(self, *, endpoint_override: str | None = None):
        import boto3

        return boto3.client("s3", **self._client_kwargs(endpoint_override=endpoint_override))

    def save(self, path: str, data: bytes, content_type: str | None = None) -> None:
        s3 = self._client()
        put_kwargs = {"Bucket": self.bucket, "Key": path, "Body": data}
        if content_type:
            put_kwargs["ContentType"] = content_type
        s3.put_object(**put_kwargs)

    def open(self, path: str, byte_range: tuple[int, int] | None = None) -> bytes:
        s3 = self._client()
        get_kwargs = {"Bucket": self.bucket, "Key": path}
        if byte_range:
            get_kwargs["Range"] = f"bytes={byte_range[0]}-{byte_range[1]}"
        response = s3.get_object(**get_kwargs)
        return response["Body"].read()

    def delete(self, path: str) -> None:
        s3 = self._client()
        s3.delete_object(Bucket=self.bucket, Key=path)

    def exists(self, path: str) -> bool:
        s3 = self._client()
        try:
            s3.head_object(Bucket=self.bucket, Key=path)
            return True
        except Exception:
            return False

    def size(self, path: str) -> int:
        s3 = self._client()
        response = s3.head_object(Bucket=self.bucket, Key=path)
        return response["ContentLength"]

    def presigned_get_url(self, path: str, ttl: int | None = None, *,
                          download_as: str | None = None) -> str:
        """Временная прямая ссылка на объект.

        ``download_as`` просит S3 отдать объект как вложение с этим именем
        файла (``ResponseContentDisposition``). Нужен для «скачать запись»:
        атрибут ``download`` у ссылки браузер игнорирует, когда файл лежит на
        другом origin (а presigned-ссылка всегда на другом), поэтому имя и
        режим вложения задаёт сам ответ хранилища. Скачивание при этом
        остаётся прямым — байты не идут через Django.
        """
        ttl_seconds = ttl if ttl is not None else self.default_presigned_ttl
        s3 = self._client(endpoint_override=self.public_endpoint)
        params = {"Bucket": self.bucket, "Key": path}
        if download_as:
            safe_name = download_as.replace('"', "").replace("\\", "")
            params["ResponseContentDisposition"] = (
                f'attachment; filename="{safe_name}"'
            )
        return s3.generate_presigned_url(
            "get_object",
            Params=params,
            ExpiresIn=ttl_seconds,
        )


def get_storage(bucket: str | None = None) -> Storage:
    """Build the configured storage backend.

    ``bucket`` lets a caller target a different S3 bucket than the cms
    default (e.g. ``apps.users.services.profile_service`` writes avatars to
    ``settings.MEDIA_S3_BUCKET`` instead of ``settings.S3_BUCKET``). Omitting
    it reproduces the original no-arg behaviour byte-for-byte — every
    existing call site (``get_storage()``) is unaffected.

    ``LocalStorage`` ignores ``bucket``: the local dev fallback has always
    used a single directory (``CMS_LOCAL_STORAGE_DIR``) with no per-bucket
    subdirectory, and introducing one now would change on-disk layout for
    the cms local-storage path for no S3-parity benefit (local mode is a
    dev-only fallback, never used in prod where STORAGE_BACKEND=s3).
    """
    if settings.STORAGE_BACKEND == "s3":
        return S3Storage(
            bucket=bucket or settings.S3_BUCKET,
            endpoint=settings.S3_ENDPOINT,
            access_key=settings.S3_ACCESS_KEY,
            secret_key=settings.S3_SECRET_KEY,
            region=settings.S3_REGION,
            use_path_style=settings.S3_USE_PATH_STYLE,
            public_endpoint=settings.S3_PUBLIC_ENDPOINT,
            default_presigned_ttl=settings.S3_PRESIGNED_URL_TTL,
        )
    return LocalStorage(base_dir=Path(settings.CMS_LOCAL_STORAGE_DIR))
