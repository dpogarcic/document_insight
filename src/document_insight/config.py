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
    jwt_secret_key: SecretStr
    jwt_algorithm: Literal["HS256"] = "HS256"
    jwt_issuer: str = "document-insight"
    jwt_audience: str = "document-insight-api"
    jwt_access_token_expire_minutes: int = Field(default=30, ge=1, le=1440)


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide validated configuration."""
    # BaseSettings supplies this required value from environment-backed sources.
    return Settings()  # type: ignore[call-arg]
