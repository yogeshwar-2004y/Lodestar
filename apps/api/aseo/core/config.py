"""Runtime configuration.

Every setting can be overridden with an environment variable of the same name
(upper-case). See `.env.example` at the repository root for documentation.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", "../../.env"), extra="ignore")

    # --- product / branding -------------------------------------------------
    product_name: str = "Lodestar"
    environment: Literal["development", "test", "staging", "production"] = "development"
    # Demo mode seeds clearly-labelled fixture data and enables fixture connectors.
    # It is refused when environment == production.
    demo_mode: bool = True

    # --- http ---------------------------------------------------------------
    api_prefix: str = "/api/v1"
    public_web_url: str = "http://localhost:3400"
    public_api_url: str = "http://localhost:8400"
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3400"])
    session_cookie_name: str = "ls_session"
    csrf_cookie_name: str = "ls_csrf"
    session_ttl_hours: int = 24 * 7
    cookie_secure: bool = False

    # --- storage ------------------------------------------------------------
    database_url: str = "postgresql+psycopg://localhost:5432/aseo"
    # Runtime role used for request handling; RLS applies to it. Migrations use database_url.
    database_app_url: str | None = None
    redis_url: str = "redis://localhost:6379/0"
    # "celery" dispatches outbox jobs to Celery workers; "inline" runs them in-process
    # (single-command local dev and tests).
    task_execution: Literal["celery", "inline", "manual"] = "inline"
    outbox_retry_base_seconds: float = 2.0
    snapshot_dir: str = "var/snapshots"

    # --- secrets ------------------------------------------------------------
    secret_key: str = "dev-insecure-change-me-dev-insecure-change-me"  # noqa: S105 — refused in production
    # Fernet key used by the local encrypted secret store. Generate with
    # `python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())"`.
    secrets_encryption_key: str | None = None
    secrets_backend: Literal["local", "aws"] = "local"

    # --- crawler ------------------------------------------------------------
    crawler_user_agent: str = "LodestarBot/1.0 (+https://lodestar.example/bot)"
    crawler_max_pages: int = 200
    crawler_max_bytes: int = 3_000_000
    crawler_timeout_seconds: float = 15.0
    crawler_concurrency_per_host: int = 2
    crawler_default_delay_seconds: float = 0.25
    # host:port pairs allowed even though they resolve to private addresses.
    # Development/test only — rejected in production.
    crawler_allowed_private_hosts: list[str] = Field(default_factory=list)

    # --- AI -----------------------------------------------------------------
    ai_provider: Literal["anthropic", "deterministic"] = "deterministic"
    anthropic_api_key: str | None = None
    ai_model: str = "claude-opus-5-5"
    ai_timeout_seconds: float = 90.0
    ai_max_retries: int = 2

    # --- integrations -------------------------------------------------------
    google_client_id: str | None = None
    google_client_secret: str | None = None
    shopify_api_key: str | None = None
    shopify_api_secret: str | None = None
    shopify_api_version: str = "2025-07"
    github_app_id: str | None = None
    github_app_private_key: str | None = None
    github_app_slug: str | None = None
    github_webhook_secret: str | None = None
    billing_provider: Literal["test", "stripe"] = "test"
    stripe_secret_key: str | None = None
    stripe_webhook_secret: str | None = None
    test_billing_webhook_secret: str = "whsec_test_local_only"  # noqa: S105 — test-mode billing only

    # --- limits -------------------------------------------------------------
    rate_limit_per_minute: int = 240
    auth_rate_limit_per_minute: int = 20

    @model_validator(mode="after")
    def _production_guards(self) -> Settings:
        if self.environment == "production":
            if self.demo_mode:
                raise ValueError("DEMO_MODE must be false in production")
            if self.crawler_allowed_private_hosts:
                raise ValueError("CRAWLER_ALLOWED_PRIVATE_HOSTS is not allowed in production")
            if self.secret_key.startswith("dev-insecure"):
                raise ValueError("SECRET_KEY must be set in production")
            if not self.secrets_encryption_key and self.secrets_backend == "local":
                raise ValueError("SECRETS_ENCRYPTION_KEY is required in production")
            if not self.cookie_secure:
                raise ValueError("COOKIE_SECURE must be true in production")
        return self

    @property
    def app_database_url(self) -> str:
        return self.database_app_url or self.database_url


@lru_cache
def get_settings() -> Settings:
    return Settings()
