from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

from bank_statement_assistant.jobs.models import ProcessingStage

StatementStatus = Literal["processing", "needs_review", "ready", "failed", "archived"]


@dataclass(frozen=True, slots=True)
class PdfEnvelope:
    page_count: int


@dataclass(frozen=True, slots=True)
class ExtractedPage:
    number: int
    text: str


@dataclass(frozen=True, slots=True)
class Statement:
    id: UUID
    account_reference: str
    original_filename: str
    content_hash: str
    source_path: Path
    page_count: int
    status: StatementStatus
    current_stage: ProcessingStage
    extracted_pages: tuple[ExtractedPage, ...] = ()
    extraction_result: dict[str, Any] | None = None
    validation_result: dict[str, Any] | None = None
    review_findings: tuple[dict[str, Any], ...] = ()
    last_error_code: str | None = None
    created_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class IngestResult:
    statement: Statement
    created: bool
