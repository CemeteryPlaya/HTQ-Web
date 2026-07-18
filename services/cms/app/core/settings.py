"""Settings — loaded from environment and .env file."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """CMS-service application settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Service identity
    service_name: str = "cms"
    service_port: int = 8008
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
    db_schema: str = "cms"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Observability
    otel_exporter_otlp_endpoint: str = "http://localhost:4317"
    log_level: str = "INFO"

    # CMS-specific
    conference_config_path: str = "app/data/conference.yaml"
    translation_api_key: str = ""
    translation_provider: str = "deepl"  # deepl (only provider wired; "" = no-op)
    translation_api_base: str = "https://api-free.deepl.com"
    contact_request_rate_limit: str = "3/minute"
    email_service_url: str = "http://email-service:8011"
    audit_log_retention_days: int = 90

    # ─── Object storage (S3 / MinIO) ─────────────────────────────────────
    # Per "1 service = 1 bucket" rule: cms owns S3_BUCKET. Layout:
    #   news/<news_id>/content.md             (snapshot of body, on publish)
    #   news/<news_id>/metadata.json          (post fields snapshot)
    #   news/<news_id>/cover.<ext>            (cover image)
    #   news/<news_id>/attachments/<id>_<filename>
    storage_backend: str = "s3"  # local | s3
    s3_bucket: str = "htqweb-cms"
    s3_endpoint: str = ""
    s3_public_endpoint: str = ""
    s3_access_key: str = ""
    s3_secret_key: str = ""
    s3_region: str = "us-east-1"
    s3_use_path_style: bool = True
    s3_presigned_url_ttl: int = 3600

    # HMAC secret for signed redirect URLs to private news attachments.
    news_signed_url_secret: str = "change-me-news-signed-secret"
    news_signed_url_ttl: int = 3600

    # Local fallback dir when STORAGE_BACKEND=local (dev without MinIO).
    cms_local_storage_dir: str = "/app/data/cms"

    @property
    def db_dsn(self) -> str:
        """Construct asyncpg DSN."""
        return (
            f"postgresql+asyncpg://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )

    @property
    def conference_yaml_path(self) -> Path:
        return Path(self.conference_config_path)


@lru_cache
def get_settings() -> Settings:
    """Cached settings singleton."""
    return Settings()


settings = get_settings()
