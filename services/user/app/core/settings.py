"""Settings — loaded from environment and .env file."""

from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Service identity
    service_name: str = "unknown-service"
    service_port: int = 8001
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
    db_schema: str = "public"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Observability
    otel_exporter_otlp_endpoint: str = "http://localhost:4317"
    log_level: str = "INFO"

    # Service-to-service (S2S) auth — shared secret for internal calls
    # (user-service → media-service when uploading avatars, etc.)
    service_jwt_secret: str = "change-me-service-secret"
    service_jwt_algorithm: str = "HS256"

    # Downstream service URLs
    media_service_url: str = "http://media-service:8009"
    email_service_url: str = "http://email-service:8011"

    @property
    def db_dsn(self) -> str:
        """Construct asyncpg DSN."""
        return (
            f"postgresql+asyncpg://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )


@lru_cache
def get_settings() -> Settings:
    """Cached settings singleton."""
    return Settings()


settings = get_settings()
