"""Provision passwords for migrated, otherwise disabled database login roles."""

import asyncio

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from document_insight.config import get_settings

_PASSWORD_SETTINGS = {
    "di_api_read_login": "database_read_password",
    "di_api_write_login": "database_write_password",
    "di_auth_login": "database_auth_password",
    "di_worker_login": "database_worker_password",
    "di_reconciler_login": "database_reconciler_password",
    "di_monitor_login": "database_monitor_password",
}


async def bootstrap_roles() -> None:
    """Enable only login roles with explicitly supplied external secrets."""
    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    try:
        async with engine.begin() as connection:
            for role, setting_name in _PASSWORD_SETTINGS.items():
                secret = getattr(settings, setting_name)
                if secret is None or not secret.get_secret_value():
                    raise ValueError(f"{setting_name.upper()} must not be empty")
                quoted = await connection.scalar(
                    text("SELECT quote_literal(:value)"), {"value": secret.get_secret_value()}
                )
                await connection.execute(text(f"ALTER ROLE {role} LOGIN PASSWORD {quoted}"))
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(bootstrap_roles())
