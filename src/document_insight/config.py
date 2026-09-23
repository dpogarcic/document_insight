"""Validated application configuration."""

from functools import lru_cache
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings loaded from environment variables or a local `.env` file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = (
        "postgresql+asyncpg://document_insight:document_insight@localhost:5432/document_insight"
    )
    database_read_url: str | None = None
    database_write_url: str | None = None
    database_auth_url: str | None = None
    database_worker_url: str | None = None
    database_reconciler_url: str | None = None
    database_monitor_url: str | None = None
    database_profile_operator_url: str | None = None
    database_read_password: SecretStr | None = None
    database_write_password: SecretStr | None = None
    database_auth_password: SecretStr | None = None
    database_worker_password: SecretStr | None = None
    database_reconciler_password: SecretStr | None = None
    database_monitor_password: SecretStr | None = None
    database_profile_operator_password: SecretStr | None = None
    database_pool_size: int = Field(default=10, ge=1)
    database_max_overflow: int = Field(default=20, ge=0)
    database_pool_timeout_seconds: int = Field(default=5, ge=1)
    admin_panel_username: str | None = None
    admin_panel_password: SecretStr | None = None
    admin_panel_secure_cookies: bool = False
    api_public_base_url: str = "http://127.0.0.1:8000"

    @field_validator("api_public_base_url")
    @classmethod
    def _valid_api_public_base_url(cls, value: str) -> str:
        """Keep the upload link on an explicit HTTP origin without embedded secrets."""
        parsed = urlsplit(value)
        try:
            hostname = parsed.hostname
            _ = parsed.port
        except ValueError as error:
            raise ValueError("API_PUBLIC_BASE_URL must be an HTTP(S) base URL") from error
        if (
            parsed.scheme not in {"http", "https"}
            or hostname is None
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("API_PUBLIC_BASE_URL must be an HTTP(S) base URL")
        return value.rstrip("/")

    evaluation_tenant_id: UUID | None = None

    @field_validator("evaluation_tenant_id", mode="before")
    @classmethod
    def _blank_evaluation_tenant(cls, value: object) -> object:
        """Allow optional Compose profile services to start before a tenant is selected."""
        return None if value == "" else value

    jwt_secret_key: SecretStr
    jwt_algorithm: Literal["HS256"] = "HS256"
    jwt_issuer: str = "document-insight"
    jwt_audience: str = "document-insight-api"
    jwt_access_token_expire_minutes: int = Field(default=30, ge=1, le=1440)
    s3_endpoint_url: str = "http://localhost:9000"
    s3_access_key: SecretStr = SecretStr("document-insight")
    s3_secret_key: SecretStr = SecretStr("document-insight-local-only")
    s3_bucket_name: str = "document-insight-originals"
    s3_region: str = "us-east-1"
    upload_max_bytes: int = Field(default=25 * 1024 * 1024, ge=10 * 1024 * 1024)
    redis_url: str = "redis://localhost:6379/0"
    query_rate_limit_requests: int = Field(default=30, ge=1, le=10_000)
    query_rate_limit_window_seconds: int = Field(default=60, ge=1, le=86_400)
    rq_ingestion_queue_name: str = "ingestion"
    rq_evaluation_queue_name: str = "evaluation"
    job_reconciliation_interval_seconds: int = Field(default=60, ge=5, le=3600)
    metrics_bearer_token: SecretStr | None = None
    prometheus_multiproc_dir: str | None = None
    mistral_base_url: str = "https://api.mistral.ai/v1"
    mistral_api_key: SecretStr | None = None
    cors_allowed_origins: tuple[str, ...] = (
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    )


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide validated configuration."""
    # BaseSettings supplies this required value from environment-backed sources.
    return Settings()  # type: ignore[call-arg]
