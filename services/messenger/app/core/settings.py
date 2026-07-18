"""Settings for Messenger Service."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Messenger-service application settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Service identity
    service_name: str = "messenger"
    service_port: int = 8010
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
    db_schema: str = "messenger"

    # Redis (for Socket.IO adapter)
    redis_url: str = "redis://localhost:6379/1"

    # Observability
    log_level: str = "INFO"
    audit_log_retention_days: int = 90

    # Attachments — legacy local volume (kept for the migration script that
    # backfills existing files into S3; routers always write to S3).
    attachment_dir: str = "/app/data/attachments"

    # ─── Object storage (S3 / MinIO) ─────────────────────────────────────
    # Per the "1 service = 1 bucket" rule: messenger owns S3_BUCKET. Layout:
    #   chats/<room_storage_key>/<data_type>/<id>_<filename>
    #   chats/<room_storage_key>/metadata/<attachment_id>.json
    #   chats/<room_storage_key>/history/<YYYY>/<MM>/<DD>.jsonl
    storage_backend: str = "s3"  # local | s3
    s3_bucket: str = "htqweb-messenger"
    s3_endpoint: str = ""
    s3_public_endpoint: str = ""  # browser-reachable host (presigned URL host)
    s3_access_key: str = ""
    s3_secret_key: str = ""
    s3_region: str = "us-east-1"
    s3_use_path_style: bool = True
    s3_presigned_url_ttl: int = 3600

    # HMAC secret for the per-attachment redirect URL we expose to the
    # browser (works inside <img src> without an Authorization header).
    attachment_signed_url_secret: str = "change-me-attachment-signed-secret"
    attachment_signed_url_ttl: int = 3600

    # Weekly history archive — Saturday 04:30 GMT+5 by default.
    history_archive_timezone: str = "Asia/Almaty"
    history_archive_cron_day: str = "sat"
    history_archive_cron_hour: int = 4
    history_archive_cron_minute: int = 30

    # Push Notifications
    fcm_api_key: str = ""
    apns_cert_path: str = ""

    @property
    def db_dsn(self) -> str:
        return (
            f"postgresql+asyncpg://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
