from pathlib import Path
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient

from bank_statement_assistant.adapters.http.app import create_app
from bank_statement_assistant.jobs.models import ProcessingStage
from bank_statement_assistant.statements.models import IngestResult, Statement

pytestmark = pytest.mark.anyio


class Ready:
    async def check(self) -> bool:
        return True


class FakeStatements:
    def __init__(self) -> None:
        self.uploads: list[tuple[str, str, bytes]] = []
        self.statement = Statement(
            id=UUID("50e5591f-913e-471b-a501-541fd860af30"),
            account_reference="BPI Main",
            original_filename="statement.pdf",
            content_hash="hash",
            source_path=Path("/private/source.pdf"),
            page_count=1,
            status="processing",
            current_stage=ProcessingStage.EXTRACT_TEXT,
        )

    def ingest(
        self, *, account_reference: str, original_filename: str, content: bytes
    ) -> IngestResult:
        self.uploads.append((account_reference, original_filename, content))
        return IngestResult(statement=self.statement, created=True)

    def list(self) -> tuple[Statement, ...]:
        return (self.statement,)

    def get(self, statement_id: UUID) -> Statement | None:
        return self.statement if statement_id == self.statement.id else None

    def retry(self, statement_id: UUID) -> Statement | None:
        return self.get(statement_id)

    def reprocess_from_source(self, statement_id: UUID) -> Statement | None:
        return self.get(statement_id)


async def test_upload_returns_visible_processing_state_without_exposing_source_path() -> None:
    statements = FakeStatements()
    app = create_app(readiness=Ready(), statements=statements)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/statements",
            data={"account_reference": "BPI Main"},
            files={"file": ("statement.pdf", b"%PDF statement", "application/pdf")},
        )

    assert response.status_code == 201
    assert response.json() == {
        "id": "50e5591f-913e-471b-a501-541fd860af30",
        "account_reference": "BPI Main",
        "original_filename": "statement.pdf",
        "page_count": 1,
        "status": "processing",
        "current_stage": "extract_text",
        "extraction_result": None,
        "validation_result": None,
        "review_findings": [],
        "last_error_code": None,
        "created_at": None,
    }
    assert statements.uploads == [("BPI Main", "statement.pdf", b"%PDF statement")]
    assert "source_path" not in response.json()


async def test_list_detail_and_missing_statement() -> None:
    statements = FakeStatements()
    app = create_app(readiness=Ready(), statements=statements)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        listing = await client.get("/api/statements")
        detail = await client.get(f"/api/statements/{statements.statement.id}")
        missing = await client.get("/api/statements/da7abe2b-aac6-42e5-ae61-669e3ca11ebb")

    assert listing.status_code == 200
    assert listing.json()[0]["id"] == str(statements.statement.id)
    assert detail.status_code == 200
    assert missing.status_code == 404


async def test_reprocess_from_source_returns_processing_statement() -> None:
    statements = FakeStatements()
    app = create_app(readiness=Ready(), statements=statements)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(f"/api/statements/{statements.statement.id}/reprocess")

    assert response.status_code == 202
    assert response.json()["id"] == str(statements.statement.id)


async def test_upload_is_rejected_before_reading_beyond_the_configured_limit() -> None:
    statements = FakeStatements()
    app = create_app(readiness=Ready(), statements=statements, max_upload_bytes=8)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/statements",
            data={"account_reference": "BPI Main"},
            files={"file": ("large.pdf", b"%PDF-1234", "application/pdf")},
        )

    assert response.status_code == 413
    assert statements.uploads == []
