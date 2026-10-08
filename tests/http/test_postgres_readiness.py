import os

import pytest
from sqlalchemy import create_engine, text

from bank_statement_assistant.adapters.postgres.health import (
    PostgresReadiness,
    SyncPostgresReadiness,
)
from bank_statement_assistant.schema import SCHEMA_HEAD


@pytest.fixture
def database_url() -> str:
    value = os.getenv("TEST_DATABASE_URL")
    if value is None:
        pytest.skip("TEST_DATABASE_URL is not configured")
    return value


@pytest.mark.anyio
@pytest.mark.postgres
async def test_readiness_requires_the_current_schema_head(database_url: str) -> None:
    async_readiness = PostgresReadiness(database_url)
    sync_readiness = SyncPostgresReadiness(database_url)
    engine = create_engine(database_url)

    assert await async_readiness.check() is True
    assert sync_readiness.check() is True

    try:
        with engine.begin() as connection:
            connection.execute(
                text("UPDATE alembic_version SET version_num = 'outdated-schema'"),
            )

        assert await async_readiness.check() is False
        assert sync_readiness.check() is False
    finally:
        with engine.begin() as connection:
            connection.execute(
                text("UPDATE alembic_version SET version_num = :schema_head"),
                {"schema_head": SCHEMA_HEAD},
            )
        engine.dispose()
