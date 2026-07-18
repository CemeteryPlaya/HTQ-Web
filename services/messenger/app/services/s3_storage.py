"""S3 storage helper for messenger-service.

Mirrors the abstraction in ``services/media/app/storage.py``. Per
``services/README.md`` services intentionally don't share a library — each
storage-owning service ships its own copy so it can evolve independently.

This module:
- writes chat attachments under ``chats/<room>/<data_type>/<id>_<file>``;
- writes per-attachment ``metadata/<id>.json`` JSON snapshots;
- writes weekly room history under ``chats/<room>/history/<YYYY>/<MM>/<DD>.jsonl``;
- mints presigned GET URLs that the browser can hit without a JWT.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Protocol, runtime_checkable

import aiofiles
import aiofiles.os

from app.core.settings import settings


@runtime_checkable
class Storage(Protocol):
    async def save(self, path: str, data: bytes, content_type: str | None = None) -> None: ...
    async def open(self, path: str, byte_range: tuple[int, int] | None = None) -> bytes: ...
    async def delete(self, path: str) -> None: ...
    async def exists(self, path: str) -> bool: ...
    async def size(self, path: str) -> int: ...
    async def presigned_get_url(self, path: str, ttl: int | None = None) -> str: ...


class LocalStorage:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _resolve(self, path: str) -> Path:
        resolved = (self.base_dir / path).resolve()
        if not str(resolved).startswith(str(self.base_dir.resolve())):
            raise ValueError(f"Path traversal detected: {path}")
        return resolved

    async def save(self, path: str, data: bytes, content_type: str | None = None) -> None:
        target = self._resolve(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        async with aiofiles.open(target, "wb") as f:
            await f.write(data)

    async def open(self, path: str, byte_range: tuple[int, int] | None = None) -> bytes:
        target = self._resolve(path)
        if not target.exists():
            raise FileNotFoundError(path)
        if byte_range is not None:
            start, end = byte_range
            length = end - start + 1
            async with aiofiles.open(target, "rb") as f:
                await f.seek(start)
                return await f.read(length)
        async with aiofiles.open(target, "rb") as f:
            return await f.read()

    async def delete(self, path: str) -> None:
        target = self._resolve(path)
        if target.exists():
            await aiofiles.os.remove(target)

    async def exists(self, path: str) -> bool:
        return self._resolve(path).exists()

    async def size(self, path: str) -> int:
        stat = await aiofiles.os.stat(self._resolve(path))
        return stat.st_size

    async def presigned_get_url(self, path: str, ttl: int | None = None) -> str:
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

    def _session_kwargs(self, *, endpoint_override: str | None = None):
        kwargs = {
            "service_name": "s3",
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

    def _session(self):
        import aioboto3

        return aioboto3.Session()

    async def save(self, path: str, data: bytes, content_type: str | None = None) -> None:
        async with self._session().client(**self._session_kwargs()) as s3:
            put_kwargs = {"Bucket": self.bucket, "Key": path, "Body": data}
            if content_type:
                put_kwargs["ContentType"] = content_type
            await s3.put_object(**put_kwargs)

    async def open(self, path: str, byte_range: tuple[int, int] | None = None) -> bytes:
        async with self._session().client(**self._session_kwargs()) as s3:
            get_kwargs = {"Bucket": self.bucket, "Key": path}
            if byte_range:
                get_kwargs["Range"] = f"bytes={byte_range[0]}-{byte_range[1]}"
            response = await s3.get_object(**get_kwargs)
            return await response["Body"].read()

    async def delete(self, path: str) -> None:
        async with self._session().client(**self._session_kwargs()) as s3:
            await s3.delete_object(Bucket=self.bucket, Key=path)

    async def exists(self, path: str) -> bool:
        async with self._session().client(**self._session_kwargs()) as s3:
            try:
                await s3.head_object(Bucket=self.bucket, Key=path)
                return True
            except Exception:
                return False

    async def size(self, path: str) -> int:
        async with self._session().client(**self._session_kwargs()) as s3:
            response = await s3.head_object(Bucket=self.bucket, Key=path)
            return response["ContentLength"]

    async def presigned_get_url(self, path: str, ttl: int | None = None) -> str:
        ttl_seconds = ttl if ttl is not None else self.default_presigned_ttl
        async with self._session().client(
            **self._session_kwargs(endpoint_override=self.public_endpoint)
        ) as s3:
            return await s3.generate_presigned_url(
                "get_object",
                Params={"Bucket": self.bucket, "Key": path},
                ExpiresIn=ttl_seconds,
            )


@lru_cache
def get_storage() -> Storage:
    """Cached factory — single instance per process."""
    if settings.storage_backend == "s3":
        return S3Storage(
            bucket=settings.s3_bucket,
            endpoint=settings.s3_endpoint,
            access_key=settings.s3_access_key,
            secret_key=settings.s3_secret_key,
            region=settings.s3_region,
            use_path_style=settings.s3_use_path_style,
            public_endpoint=settings.s3_public_endpoint,
            default_presigned_ttl=settings.s3_presigned_url_ttl,
        )
    return LocalStorage(base_dir=Path(settings.attachment_dir))
