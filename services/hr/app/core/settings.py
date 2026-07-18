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
    service_name: str = "hr-service"
    service_port: int = 8006
    service_env: str = "development"

    # HR-specific
    api_prefix: str = "/api/hr/v1"

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

    # Downstream services
    media_service_url: str = "http://media-service:8009"
    user_service_url: str = "http://user-service:8005"

    # Public-facing base URL used to build shareable link URLs (e.g.
    # ``https://htq.example.com``). Empty string means: derive from request.
    public_base_url: str = ""

    # Google Cloud Translation Basic v2. Empty key disables automatic org-tree
    # translation. If empty, the service can use a self-hosted LibreTranslate
    # endpoint configured below.
    google_translate_api_key: str = ""
    google_translate_api_base: str = "https://translation.googleapis.com/language/translate/v2"
    libre_translate_api_url: str = ""
    libre_translate_api_key: str = ""

    # MongoDB (async via motor) — stores HR documents and bulky employee files.
    # When empty, the service falls back to SQL-only document storage.
    mongo_uri: str = ""
    mongo_db_name: str = "htqweb_docs"

    # Auto-seed demo HR data (departments, positions, employees, PMOs) on
    # service startup if the demo records are not yet present. Always disabled
    # in production regardless of this flag.
    auto_seed_demo: bool = True

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
