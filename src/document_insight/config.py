"""Validated application configuration."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
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
    database_read_password: SecretStr | None = None
    database_write_password: SecretStr | None = None
    database_auth_password: SecretStr | None = None
    database_worker_password: SecretStr | None = None
    database_reconciler_password: SecretStr | None = None
    database_monitor_password: SecretStr | None = None
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
    rq_ingestion_queue_name: str = "ingestion"
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
