from dataclasses import replace
from pathlib import Path
from uuid import UUID

from bank_statement_assistant.jobs.models import ProcessingStage
from bank_statement_assistant.statements.application import StatementApplication
from bank_statement_assistant.statements.models import ExtractedPage, IngestResult, Statement


class RecordingStatements:
    def __init__(self, statement: Statement) -> None:
        self.statement = statement
        self.restarts: list[UUID] = []
        self.source_reprocesses: list[UUID] = []

    def list(self, *, limit: int = 100) -> tuple[Statement, ...]:
        return (self.statement,)

    def get(self, statement_id: UUID) -> Statement | None:
        return self.statement if statement_id == self.statement.id else None

    def restart_with_job(self, *, statement_id: UUID) -> Statement:
        self.restarts.append(statement_id)
        return replace(self.statement, status="processing", last_error_code=None)

    def reprocess_from_source(self, *, statement_id: UUID) -> Statement:
        self.source_reprocesses.append(statement_id)
        return replace(
            self.statement,
            status="processing",
            current_stage=ProcessingStage.EXTRACT_TEXT,
            extracted_pages=(),
            extraction_result=None,
            validation_result=None,
            review_findings=(),
            last_error_code=None,
        )


def test_retry_uses_the_repository_atomic_restart_and_enqueue_boundary() -> None:
    statement = Statement(
        id=UUID("50e5591f-913e-471b-a501-541fd860af30"),
        account_reference="BPI Main",
        original_filename="statement.pdf",
        content_hash="hash",
        source_path=Path("/private/statement.pdf"),
        page_count=1,
        status="failed",
        current_stage=ProcessingStage.VALIDATE,
        last_error_code="validate_failed",
    )
    statements = RecordingStatements(statement)
    application = StatementApplication(
        ingest=lambda **_values: IngestResult(statement=statement, created=True),
        statements=statements,
    )

    retried = application.retry(statement.id)

    assert retried is not None
    assert retried.status == "processing"
    assert retried.last_error_code is None
    assert statements.restarts == [statement.id]


def test_retry_requeues_a_failed_classification_stage() -> None:
    statement = Statement(
        id=UUID("50e5591f-913e-471b-a501-541fd860af30"),
        account_reference="BPI Main",
        original_filename="statement.pdf",
        content_hash="hash",
        source_path=Path("/private/statement.pdf"),
        page_count=1,
        status="failed",
        current_stage=ProcessingStage.CLASSIFY,
        last_error_code="classify_invalid_response",
    )
    statements = RecordingStatements(statement)
    application = StatementApplication(
        ingest=lambda **_values: IngestResult(statement=statement, created=True),
        statements=statements,
    )

    retried = application.retry(statement.id)

    assert retried is not None
    assert retried.status == "processing"
    assert retried.current_stage == ProcessingStage.CLASSIFY
    assert retried.last_error_code is None
    assert statements.restarts == [statement.id]


def test_reprocess_from_source_uses_a_distinct_repository_operation() -> None:
    statement = Statement(
        id=UUID("50e5591f-913e-471b-a501-541fd860af30"),
        account_reference="BPI Main",
        original_filename="statement.pdf",
        content_hash="hash",
        source_path=Path("/private/statement.pdf"),
        page_count=1,
        status="failed",
        current_stage=ProcessingStage.EXTRACT_TRANSACTIONS,
        extracted_pages=(ExtractedPage(number=1, text="stale"),),
        last_error_code="extract_transactions_failed",
    )
    statements = RecordingStatements(statement)
    application = StatementApplication(
        ingest=lambda **_values: IngestResult(statement=statement, created=True),
        statements=statements,
    )

    reprocessed = application.reprocess_from_source(statement.id)

    assert reprocessed is not None
    assert reprocessed.status == "processing"
    assert reprocessed.current_stage == ProcessingStage.EXTRACT_TEXT
    assert statements.source_reprocesses == [statement.id]
