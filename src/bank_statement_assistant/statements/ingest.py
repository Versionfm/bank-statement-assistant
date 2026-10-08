from hashlib import sha256
from logging import getLogger
from pathlib import Path
from typing import Protocol
from uuid import UUID, uuid4

from bank_statement_assistant.jobs.models import ProcessingStage
from bank_statement_assistant.statements.models import IngestResult, PdfEnvelope, Statement

_logger = getLogger(__name__)


class PdfInspector(Protocol):
    def inspect(self, *, original_filename: str, content: bytes) -> PdfEnvelope: ...


class StatementFileStore(Protocol):
    def store(self, *, statement_id: UUID, content: bytes) -> Path: ...

    def delete(self, *, path: Path) -> None: ...


class StatementRepository(Protocol):
    def find_by_content_hash(self, content_hash: str) -> Statement | None: ...

    def create_with_job(
        self,
        *,
        statement: Statement,
        stage: ProcessingStage,
        payload: dict[str, object],
    ) -> Statement: ...


class IngestStatement:
    def __init__(
        self,
        *,
        statements: StatementRepository,
        files: StatementFileStore,
        pdfs: PdfInspector,
    ) -> None:
        self._statements = statements
        self._files = files
        self._pdfs = pdfs

    def __call__(
        self,
        *,
        account_reference: str,
        original_filename: str,
        content: bytes,
    ) -> IngestResult:
        account_reference = account_reference.strip()
        if not account_reference:
            raise ValueError("account_reference must not be empty")

        envelope = self._pdfs.inspect(
            original_filename=original_filename,
            content=content,
        )
        content_hash = sha256(content).hexdigest()
        duplicate = self._statements.find_by_content_hash(content_hash)
        if duplicate is not None:
            _logger.info(
                "statement_duplicate_returned",
                extra={
                    "statement_id": str(duplicate.id),
                    "content_hash_prefix": content_hash[:12],
                },
            )
            return IngestResult(statement=duplicate, created=False)

        statement_id = uuid4()
        source_path = self._files.store(statement_id=statement_id, content=content)
        statement = Statement(
            id=statement_id,
            account_reference=account_reference,
            original_filename=original_filename,
            content_hash=content_hash,
            source_path=source_path,
            page_count=envelope.page_count,
            status="processing",
            current_stage=ProcessingStage.EXTRACT_TEXT,
        )
        try:
            statement = self._statements.create_with_job(
                statement=statement,
                stage=ProcessingStage.EXTRACT_TEXT,
                payload={"source_path": str(statement.source_path)},
            )
        except Exception:
            self._files.delete(path=source_path)
            raise
        _logger.info(
            "statement_ingested",
            extra={
                "statement_id": str(statement.id),
                "page_count": statement.page_count,
                "content_hash_prefix": content_hash[:12],
            },
        )
        return IngestResult(statement=statement, created=True)
