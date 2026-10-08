from uuid import UUID

from bank_statement_assistant.adapters.postgres.statements import PostgresStatementRepository
from bank_statement_assistant.statements.resolution import (
    ClassificationAcceptance,
    CorrectionCommand,
    CorrectionRecord,
    RevertCommand,
)
from bank_statement_assistant.statements.transactions import (
    Transaction,
    TransactionFilters,
    TransactionPage,
)


class PostgresTransactionRepository:
    """Read-side transaction adapter kept separate from statement lookup methods."""

    def __init__(self, database_url: str) -> None:
        self._statements = PostgresStatementRepository(database_url)

    def dispose(self) -> None:
        self._statements.dispose()

    def list(self, *, filters: TransactionFilters) -> TransactionPage:
        return self._statements.list_transactions(filters=filters)

    def get(self, transaction_id: UUID) -> Transaction | None:
        return self._statements.get_transaction(transaction_id)

    def correct(self, transaction_id: UUID, command: CorrectionCommand) -> Transaction:
        return self._statements.correct_transaction(transaction_id, command)

    def history(self, transaction_id: UUID) -> tuple[CorrectionRecord, ...]:
        return self._statements.transaction_history(transaction_id)

    def revert(self, transaction_id: UUID, command: RevertCommand) -> Transaction:
        return self._statements.revert_transaction(transaction_id, command)

    def accept_classification(
        self, transaction_id: UUID, acceptance: ClassificationAcceptance
    ) -> Transaction:
        return self._statements.accept_classification(transaction_id, acceptance)
