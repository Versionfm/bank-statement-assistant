from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import create_async_engine

from bank_statement_assistant.config import Settings
from bank_statement_assistant.schema import SCHEMA_HEAD

_SCHEMA_READY_QUERY = text(
    "SELECT EXISTS (SELECT 1 FROM alembic_version WHERE version_num = :schema_head)"
)


class PostgresReadiness:
    def __init__(self, database_url: str) -> None:
        self._engine = create_async_engine(
            database_url,
            pool_pre_ping=True,
            connect_args={"connect_timeout": 5, "options": "-c statement_timeout=5000"},
        )

    async def check(self) -> bool:
        try:
            async with self._engine.connect() as connection:
                result = await connection.execute(
                    _SCHEMA_READY_QUERY,
                    {"schema_head": SCHEMA_HEAD},
                )
        except SQLAlchemyError:
            return False
        return bool(result.scalar_one())


class SyncPostgresReadiness:
    def __init__(self, database_url: str) -> None:
        self._engine: Engine = create_engine(
            database_url,
            pool_pre_ping=True,
            connect_args={"connect_timeout": 5, "options": "-c statement_timeout=5000"},
        )

    def check(self) -> bool:
        try:
            with self._engine.connect() as connection:
                result = connection.execute(
                    _SCHEMA_READY_QUERY,
                    {"schema_head": SCHEMA_HEAD},
                )
        except SQLAlchemyError:
            return False
        return bool(result.scalar_one())


def run() -> None:
    settings = Settings()  # type: ignore[call-arg]
    readiness = SyncPostgresReadiness(settings.database_url)
    raise SystemExit(0 if readiness.check() else 1)
