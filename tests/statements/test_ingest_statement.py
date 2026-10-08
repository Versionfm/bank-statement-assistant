from pathlib import Path
from uuid import UUID

import pytest

from bank_statement_assistant.jobs.models import ProcessingStage
from bank_statement_assistant.statements.ingest import IngestStatement
from bank_statement_assistant.statements.models import PdfEnvelope, Statement


class AcceptingPdfInspector:
    def inspect(self, *, original_filename: str, content: bytes) -> PdfEnvelope:
        return PdfEnvelope(page_count=2)


class RejectingPdfInspector:
    def inspect(self, *, original_filename: str, content: bytes) -> PdfEnvelope:
        raise ValueError("invalid PDF")


class RecordingFileStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.writes: list[tuple[UUID, bytes]] = []

    def store(self, *, statement_id: UUID, content: bytes) -> Path:
        self.writes.append((statement_id, content))
        return self.root / f"{statement_id}.pdf"

    def delete(self, *, path: Path) -> None:
        raise AssertionError(f"unexpected cleanup of {path}")


class DeletingFileStore(RecordingFileStore):
    def __init__(self, root: Path) -> None:
        super().__init__(root)
        self.deleted: list[Path] = []

    def delete(self, *, path: Path) -> None:
        self.deleted.append(path)


class RecordingStatements:
    def __init__(self, *, duplicate: Statement | None = None) -> None:
        self.created: list[Statement] = []
        self.duplicate = duplicate
        self.enqueued: list[dict[str, object]] = []

    def find_by_content_hash(self, content_hash: str) -> Statement | None:
        return self.duplicate

    def create_with_job(self, **values: object) -> Statement:
        statement = values["statement"]
        assert isinstance(statement, Statement)
        self.created.append(statement)
        self.enqueued.append(values)
        return statement


class FailingStatements(RecordingStatements):
    def create_with_job(self, **values: object) -> Statement:
        raise RuntimeError("database unavailable")


def test_ingest_accepts_a_pdf_stores_it_and_queues_text_extraction(tmp_path: Path) -> None:
    statements = RecordingStatements()
    files = RecordingFileStore(tmp_path)
    ingest = IngestStatement(
        statements=statements,
        files=files,
        pdfs=AcceptingPdfInspector(),
    )

    result = ingest(
        account_reference="BPI Main",
        original_filename="statement.pdf",
        content=b"%PDF synthetic",
    )

    assert result.created is True
    assert result.statement.account_reference == "BPI Main"
    assert result.statement.original_filename == "statement.pdf"
    assert result.statement.page_count == 2
    assert result.statement.status == "processing"
    assert result.statement.current_stage == ProcessingStage.EXTRACT_TEXT
    assert files.writes == [(result.statement.id, b"%PDF synthetic")]
    assert statements.created == [result.statement]
    assert statements.enqueued == [
        {
            "statement": result.statement,
            "stage": ProcessingStage.EXTRACT_TEXT,
            "payload": {"source_path": str(result.statement.source_path)},
        }
    ]


def test_ingest_returns_an_existing_statement_without_writing_or_queuing(
    tmp_path: Path,
) -> None:
    duplicate = Statement(
        id=UUID("50e5591f-913e-471b-a501-541fd860af30"),
        account_reference="BPI Main",
        original_filename="first.pdf",
        content_hash="existing",
        source_path=tmp_path / "existing.pdf",
        page_count=2,
        status="ready",
        current_stage=ProcessingStage.PUBLISH_STATE,
    )
    statements = RecordingStatements(duplicate=duplicate)
    files = RecordingFileStore(tmp_path)
    ingest = IngestStatement(
        statements=statements,
        files=files,
        pdfs=AcceptingPdfInspector(),
    )

    result = ingest(
        account_reference="BPI Main",
        original_filename="copy.pdf",
        content=b"%PDF duplicate",
    )

    assert result == result.__class__(statement=duplicate, created=False)
    assert files.writes == []
    assert statements.created == []
    assert statements.enqueued == []


def test_ingest_rejects_an_invalid_pdf_before_storing_anything(tmp_path: Path) -> None:
    statements = RecordingStatements()
    files = RecordingFileStore(tmp_path)
    ingest = IngestStatement(
        statements=statements,
        files=files,
        pdfs=RejectingPdfInspector(),
    )

    try:
        ingest(
            account_reference="BPI Main",
            original_filename="malicious.pdf",
            content=b"not a PDF",
        )
    except ValueError as error:
        assert str(error) == "invalid PDF"
    else:
        raise AssertionError("invalid PDF was accepted")

    assert files.writes == []
    assert statements.created == []
    assert statements.enqueued == []


def test_ingest_removes_the_source_when_atomic_create_and_enqueue_rolls_back(
    tmp_path: Path,
) -> None:
    statements = FailingStatements()
    files = DeletingFileStore(tmp_path)
    ingest = IngestStatement(
        statements=statements,
        files=files,
        pdfs=AcceptingPdfInspector(),
    )

    with pytest.raises(RuntimeError, match="database unavailable"):
        ingest(
            account_reference="BPI Main",
            original_filename="statement.pdf",
            content=b"%PDF synthetic",
        )

    assert len(files.writes) == 1
    assert files.deleted == [tmp_path / f"{files.writes[0][0]}.pdf"]
