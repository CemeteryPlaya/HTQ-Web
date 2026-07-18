"""Settings for Email Service."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Email-service application settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Service identity
    service_name: str = "email"
    service_port: int = 8011
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
    db_schema: str = "email"

    # Redis
    redis_url: str = "redis://localhost:6379/2"

    # Observability
    log_level: str = "INFO"

    # Crypto (must be 32 bytes hex for AES-256-GCM)
    encryption_key: str = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"

    # OAuth — provider apps
    google_client_id: str = ""
    google_client_secret: str = ""
    google_oauth_redirect_uri: str = "http://localhost:3000/email/oauth/callback/"
    microsoft_client_id: str = ""
    microsoft_client_secret: str = ""
    microsoft_oauth_redirect_uri: str = "http://localhost:3000/email/oauth/callback/"
    microsoft_oauth_tenant_id: str = "common"

    # OAuth — flow state (PKCE nonce TTL in Redis)
    oauth_state_ttl_sec: int = 600
    # Where the SPA is served — used by /oauth/callback to redirect users
    # back to the email page after a successful exchange.
    frontend_base_url: str = "http://localhost:3000"

    # ── Sync ────────────────────────────────────────────────────────────────
    # Number of recent messages per folder fetched on initial backfill.
    sync_initial_backfill_count: int = 200
    # Skip attachments larger than this (bytes) — we won't pull them into S3.
    attachment_max_bytes: int = 26_214_400  # 25 MB

    # ── Push (Phase 5) ─────────────────────────────────────────────────────
    # Public URL where providers can reach our webhook receivers; used to
    # build `notificationUrl` for Microsoft Graph subscriptions.
    webhook_base_url: str = ""
    # Gmail Pub/Sub topic name (full path, e.g. projects/htqweb/topics/gmail-push)
    google_pubsub_topic: str = ""
    # Token query-param checked on every Gmail webhook request.
    google_pubsub_verification_token: str = ""
    # Microsoft passes this back on every notification — must match.
    microsoft_webhook_client_state: str = ""
    # How long subscription/watch should live; provider caps:
    #   Gmail watch        → ≤ 7 days
    #   Outlook /me/messages /delta → ≤ 4230 minutes (~3 days)
    push_subscription_ttl_minutes: int = 4200

    # Audit log retention (consumed by scheduler.audit_log_compaction).
    audit_log_retention_days: int = 90

    # Stage-2 mailbox purge: archived mailboxes older than this are
    # hard-deleted from Mailcow (and our row marked status='deleted').
    mailbox_purge_after_days: int = 30
    # Same idea for personal accounts whose user was deleted.
    email_message_purge_on_account_delete: bool = False

    # ── Object storage (S3 / MinIO) for attachments ────────────────────────
    storage_backend: str = "s3"  # local | s3
    s3_bucket: str = "htqweb-mail-attachments"
    s3_endpoint: str = ""
    s3_public_endpoint: str = ""
    s3_access_key: str = ""
    s3_secret_key: str = ""
    s3_region: str = "us-east-1"
    s3_use_path_style: bool = True
    s3_presigned_url_ttl: int = 3600
    email_local_storage_dir: str = "/app/data/email"

    # ── Mailcow provisioning ────────────────────────────────────────────────
    # Endpoint of Mailcow's REST API (https://<mailcow-host>/api/v1).
    # API key needs both "Read" and "Read-Write" rights for /add/mailbox,
    # /edit/mailbox, /delete/mailbox, /add/alias and forwarding endpoints.
    # Generate one at: Mailcow UI → System → Configuration → Access → API.
    mailcow_api_url: str = ""
    mailcow_api_key: str = ""
    mailcow_domain: str = ""
    mailcow_default_quota_mb: int = 1024
    # Service-to-service auth — must match user-service's SERVICE_JWT_SECRET so
    # the user-service hook (POST /admin/users/) can call the mailbox endpoints.
    service_jwt_secret: str = "change-me-service-secret"
    service_jwt_algorithm: str = "HS256"

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
