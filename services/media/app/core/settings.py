"""Settings — loaded from environment and .env file."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Media-service application settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Service identity
    service_name: str = "media"
    service_port: int = 8009
    service_env: str = "development"

    # JWT
    jwt_secret: str = "change-me"
    jwt_algorithm: str = "HS256"
    jwt_issuer: str = "htqweb-auth"

    # Database
    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str = "htqweb"
    db_user: str = "htqweb"
    db_password: str = "change-me"
    db_schema: str = "media"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Observability
    otel_exporter_otlp_endpoint: str = "http://localhost:4317"
    log_level: str = "INFO"

    # Service-to-service auth — MUST match user-service.service_jwt_secret.
    # A valid service JWT bypasses the regular user-JWT user_id check and is
    # trusted for cross-service uploads (e.g., user-service posting avatars).
    service_jwt_secret: str = "change-me-service-secret"
    service_jwt_algorithm: str = "HS256"

    # Storage
    storage_backend: str = "local"  # local | s3
    media_root: str = "/app/data/media"

    # S3 (optional)
    s3_bucket: str = ""
    s3_endpoint: str = ""
    s3_access_key: str = ""
    s3_secret_key: str = ""
    s3_region: str = "us-east-1"
    # MinIO and other non-AWS providers usually require path-style addressing
    # (http://host/bucket/key) instead of virtual-hosted-style. Set to True
    # in dev (MinIO), False for AWS S3 in prod.
    s3_use_path_style: bool = True
    # Endpoint the BROWSER will hit when redirected to a presigned URL. In dev
    # this is http://localhost:9000 (MinIO), in prod the public S3 / CDN host.
    # When empty, falls back to s3_endpoint.
    s3_public_endpoint: str = ""
    # Default TTL for presigned GET URLs.
    s3_presigned_url_ttl: int = 3600

    # Limits
    max_upload_size_mb: int = 100
    allowed_mime_types: str = ""  # comma-separated, empty = allow all

    audit_log_retention_days: int = 90

    # Image processing
    image_jpeg_quality: int = 85
    thumbnail_format: str = "webp"  # webp | jpeg | png
    thumbnail_quality: int = 82
    max_image_pixels: int = 100_000_000  # 100 megapixels — guard against image-bombs
    strip_exif: bool = True

    # Signed URLs (for private files served via <img> without an auth header)
    media_signed_url_secret: str = "change-me-signed-url-secret"
    media_signed_url_ttl: int = 3600  # seconds; 1h default

    # Soft-delete
    soft_delete_grace_days: int = 30  # purge after N days

    # Dedup of identical content (sha256 match within same scope+owner)
    dedup_enabled: bool = False

    @property
    def db_dsn(self) -> str:
        return (
            f"postgresql+asyncpg://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )

    @property
    def media_root_path(self) -> Path:
        return Path(self.media_root)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
