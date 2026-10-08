from collections.abc import Callable
from logging import getLogger
from typing import Protocol
from uuid import UUID

from bank_statement_assistant.statements.models import IngestResult, Statement

_logger = getLogger(__name__)


class StatementRepository(Protocol):
    def list(self, *, limit: int = 100) -> tuple[Statement, ...]: ...

    def get(self, statement_id: UUID) -> Statement | None: ...

    def restart_with_job(self, *, statement_id: UUID) -> Statement: ...

    def reprocess_from_source(self, *, statement_id: UUID) -> Statement | None: ...


Ingest = Callable[..., IngestResult]


class StatementApplication:
    def __init__(
        self,
        *,
        ingest: Ingest,
        statements: StatementRepository,
    ) -> None:
        self._ingest = ingest
        self._statements = statements

    def ingest(
        self,
        *,
        account_reference: str,
        original_filename: str,
        content: bytes,
    ) -> IngestResult:
        return self._ingest(
            account_reference=account_reference,
            original_filename=original_filename,
            content=content,
        )

    def list(self) -> tuple[Statement, ...]:
        return self._statements.list()

    def get(self, statement_id: UUID) -> Statement | None:
        return self._statements.get(statement_id)

    def retry(self, statement_id: UUID) -> Statement | None:
        statement = self._statements.get(statement_id)
        if statement is None:
            return None
        if statement.status != "failed":
            return statement
        return self._statements.restart_with_job(statement_id=statement.id)

    def reprocess_from_source(self, statement_id: UUID) -> Statement | None:
        statement = self._statements.reprocess_from_source(statement_id=statement_id)
        if statement is not None:
            _logger.info(
                "statement_source_reprocess_requested",
                extra={"statement_id": str(statement.id)},
            )
        return statement
