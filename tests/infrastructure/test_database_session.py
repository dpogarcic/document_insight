"""Pool sizing and asyncpg settings applied only to real PostgreSQL engines."""

import pytest
from pydantic import SecretStr

from document_insight.config import Settings
from document_insight.infrastructure.database import session as session_module
from document_insight.infrastructure.database.session import get_engine


def _settings(database_url: str | None = None) -> Settings:
    kwargs: dict[str, object] = {
        "jwt_secret_key": SecretStr("test-only-secret"),
        "database_pool_size": 7,
        "database_max_overflow": 13,
        "database_pool_timeout_seconds": 3,
        # Explicit None overrides take precedence over any real DATABASE_READ_URL
        # etc. loaded from the developer's own .env file during this test.
        "database_read_url": None,
        "database_write_url": None,
        "database_auth_url": None,
        "database_worker_url": None,
        "database_reconciler_url": None,
        "database_monitor_url": None,
        "database_profile_operator_url": None,
    }
    if database_url is not None:
        kwargs["database_url"] = database_url
    return Settings(**kwargs)  # type: ignore[arg-type]


def test_postgres_engines_get_explicit_pool_size_and_disabled_statement_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A configured pool_size/max_overflow and asyncpg statement_cache_size=0 apply."""
    monkeypatch.setattr(session_module, "get_settings", lambda: _settings())
    kwargs = session_module._postgres_engine_kwargs()  # noqa: SLF001
    assert kwargs["pool_size"] == 7
    assert kwargs["max_overflow"] == 13
    assert kwargs["pool_timeout"] == 3
    assert kwargs["connect_args"] == {"statement_cache_size": 0}


def test_sqlite_engine_does_not_receive_postgres_only_pool_kwargs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A sqlite URL (used by unit tests) must not receive QueuePool-only kwargs."""
    monkeypatch.setattr(
        session_module,
        "get_settings",
        lambda: _settings(database_url="sqlite+aiosqlite:///:memory:"),
    )
    get_engine.cache_clear()
    try:
        engine = get_engine("read")
        assert engine.dialect.name == "sqlite"
    finally:
        get_engine.cache_clear()
