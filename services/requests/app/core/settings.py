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
    service_name: str = "requests-service"
    service_port: int = 8013
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
    # NOTE: the shared pgbouncer ignores the `search_path` startup param
    # (ignore_startup_parameters), so a dedicated per-service schema is not
    # reachable at runtime. The fleet convention is the `public` schema with
    # table-name prefixes (e.g. request_users), matching task-service.
    db_schema: str = "public"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Observability
    otel_exporter_otlp_endpoint: str = "http://localhost:4317"
    log_level: str = "INFO"

    # Bot integration (S2S to messenger)
    messenger_internal_url: str = "http://messenger-service:8008"
    messenger_internal_token: str = "internal-dev-secret"

    # Cross-service S2S (hr supervisor lookup, etc.)
    hr_internal_url: str = "http://hr-service:8006"
    internal_s2s_token: str = "internal-dev-secret"

    # Reminder / escalation cadence (hours)
    requests_reminder_after_hours: int = 24
    requests_escalation_after_hours: int = 72
    requests_reminder_max_iterations: int = 3

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
