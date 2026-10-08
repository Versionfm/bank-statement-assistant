from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

from bank_statement_assistant.jobs.models import ProcessingJob, ProcessingStage
from bank_statement_assistant.statements.classification import (
    CLASSIFICATION_RULE_VERSION,
    ClassificationDecision,
    ClassificationInput,
    ClassificationNormalization,
    ClassificationResult,
)
from bank_statement_assistant.statements.extraction import StatementExtraction
from bank_statement_assistant.statements.models import ExtractedPage, Statement
from bank_statement_assistant.statements.processing import StatementStageHandlers
from bank_statement_assistant.statements.resolution import TransactionValues


class FakeStatements:
    def __init__(self, statement: Statement) -> None:
        self.statement = statement
        self.stages: list[ProcessingStage] = []
        self.normalizations: tuple[ClassificationNormalization, ...] = ()

    def get(self, statement_id: UUID) -> Statement | None:
        return self.statement if statement_id == self.statement.id else None

    def save_extracted_pages_and_enqueue(
        self,
        *,
        statement_id: UUID,
        pages: tuple[ExtractedPage, ...],
        predecessor_job_id: UUID,
        next_stage: ProcessingStage,
    ) -> Statement:
        self.stages.append(next_stage)
        self.statement = replace(
            self.statement,
            extracted_pages=pages,
            current_stage=ProcessingStage.EXTRACT_TRANSACTIONS,
        )
        return self.statement

    def save_extraction_and_enqueue(
        self,
        *,
        statement_id: UUID,
        result: dict[str, Any],
        predecessor_job_id: UUID,
        next_stage: ProcessingStage,
    ) -> Statement:
        self.stages.append(next_stage)
        self.statement = replace(
            self.statement,
            extraction_result=result,
            current_stage=ProcessingStage.VALIDATE,
        )
        return self.statement

    def save_validation_and_enqueue(
        self,
        *,
        statement_id: UUID,
        result: dict[str, Any],
        findings: list[dict[str, Any]],
        predecessor_job_id: UUID,
        next_stage: ProcessingStage,
        correction_revision: int = 0,
    ) -> Statement:
        self.stages.append(next_stage)
        self.statement = replace(
            self.statement,
            validation_result=result,
            review_findings=tuple(findings),
            current_stage=next_stage,
        )
        return self.statement

    def list_classification_inputs(self, *, statement_id: UUID) -> tuple[ClassificationInput, ...]:
        assert statement_id == self.statement.id
        return (
            ClassificationInput(
                source_ordinal=1,
                booking_date=datetime(2026, 8, 2, tzinfo=UTC).date(),
                description="Groceries",
                signed_amount=-20,
                currency="EUR",
            ),
        )

    def save_classifications_and_enqueue(
        self,
        *,
        statement_id: UUID,
        decisions: tuple[ClassificationDecision, ...],
        normalizations: tuple[ClassificationNormalization, ...] = (),
        provenance: dict[str, Any],
        predecessor_job_id: UUID,
        next_stage: ProcessingStage,
    ) -> Statement:
        assert statement_id == self.statement.id
        assert decisions[0].reporting_category == "Groceries"
        assert provenance["taxonomy_version"] == "classification-v1"
        assert provenance["classification_rule_version"] == CLASSIFICATION_RULE_VERSION
        assert provenance["model"] == "unknown"
        self.normalizations = normalizations
        self.stages.append(next_stage)
        self.statement = replace(self.statement, current_stage=next_stage)
        return self.statement

    def all_transactions_classified(self, *, statement_id: UUID) -> bool:
        assert statement_id == self.statement.id
        return True

    def all_transactions_resolved(self, *, statement_id: UUID) -> bool:
        assert statement_id == self.statement.id
        return True

    def list_effective_values(self, *, statement_id: UUID) -> tuple[TransactionValues, ...]:
        assert statement_id == self.statement.id
        return (
            TransactionValues(
                booking_date=datetime(2026, 8, 2, tzinfo=UTC).date(),
                description="Groceries",
                signed_amount=Decimal("-20.00"),
                currency="EUR",
            ),
        )

    def current_correction_revision(self, *, statement_id: UUID) -> int:
        assert statement_id == self.statement.id
        return 2

    def publish_status(self, *, statement_id: UUID, ready: bool) -> Statement:
        self.statement = replace(
            self.statement,
            status="ready" if ready else "needs_review",
            current_stage=ProcessingStage.PUBLISH_STATE,
        )
        return self.statement


class FakePdfReader:
    def extract_text(self, *, content: bytes) -> tuple[ExtractedPage, ...]:
        assert content == b"%PDF statement"
        return (
            ExtractedPage(
                number=1,
                text=(
                    "Opening 100\nTransaction Count: 1\n2026-08-02 Groceries -20 EUR\nClosing 80"
                ),
            ),
        )


class FakeExtractor:
    def extract(self, pages: tuple[ExtractedPage, ...]) -> StatementExtraction:
        assert pages[0].number == 1
        return StatementExtraction.model_validate(
            {
                "account_holder": "Ana Example",
                "currency": "EUR",
                "opening_balance": "100.00",
                "closing_balance": "80.00",
                "source_transaction_count": 1,
                "source_transaction_count_evidence_page_number": 1,
                "source_transaction_count_evidence_quote": "Transaction Count: 1",
                "transactions": [
                    {
                        "booking_date": "2026-08-02",
                        "description": "Groceries",
                        "signed_amount": "-20.00",
                        "currency": "EUR",
                        "evidence_page_number": 1,
                        "evidence_quote": "2026-08-02 Groceries -20 EUR",
                        "confidence": 0.99,
                    }
                ],
                "provenance": {
                    "detector_version": "test-detector-v1",
                    "detected_bank": "bpi",
                    "layout_id": "bpi.standard.v1",
                    "routing_evidence": ["issuer-marker:bpi"],
                    "parser_id": "bpi.standard.v1",
                    "parser_version": "1",
                    "extraction_strategy": "deterministic",
                    "automatic_acceptance_eligible": True,
                },
            }
        )


class FakeClassifier:
    def classify(self, transactions: tuple[ClassificationInput, ...]) -> ClassificationResult:
        assert transactions[0].description == "Groceries"
        return ClassificationResult(
            decisions=(
                ClassificationDecision(
                    source_ordinal=1,
                    reporting_category="Groceries",
                    movement_kind="Expense",
                    payment_channel="Card",
                    confidence=0.99,
                    rationale="Grocery merchant description",
                ),
            ),
            normalizations=(
                ClassificationNormalization(
                    source_ordinal=1,
                    rule_id="transfer_reporting_category_nullification_v1",
                ),
            ),
        )


def job(
    statement_id: UUID,
    stage: ProcessingStage,
    payload: dict[str, Any] | None = None,
) -> ProcessingJob:
    now = datetime.now(UTC)
    return ProcessingJob(
        id=UUID("afeb3237-5f15-47b2-9efc-b0a9af750ace"),
        statement_id=statement_id,
        stage=stage,
        payload=payload or {},
        status="running",
        priority=0,
        attempts=1,
        available_at=now,
        claimed_at=now,
        claimed_by="test-worker",
        lease_expires_at=now,
    )


def test_stage_handlers_progress_from_source_to_deterministically_validated_review(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "statement.pdf"
    source_path.write_bytes(b"%PDF statement")
    statement = Statement(
        id=UUID("50e5591f-913e-471b-a501-541fd860af30"),
        account_reference="BPI Main",
        original_filename="statement.pdf",
        content_hash="hash",
        source_path=source_path,
        page_count=1,
        status="processing",
        current_stage=ProcessingStage.EXTRACT_TEXT,
    )
    statements = FakeStatements(statement)
    handlers = StatementStageHandlers(
        statements=statements,
        pdfs=FakePdfReader(),
        extractor=FakeExtractor(),
        classifier=FakeClassifier(),
    ).handlers()

    for stage in (
        ProcessingStage.EXTRACT_TEXT,
        ProcessingStage.EXTRACT_TRANSACTIONS,
        ProcessingStage.VALIDATE,
        ProcessingStage.CLASSIFY,
        ProcessingStage.REVIEW,
    ):
        handlers[stage](job(statement.id, stage))

    assert statements.stages == [
        ProcessingStage.EXTRACT_TRANSACTIONS,
        ProcessingStage.VALIDATE,
        ProcessingStage.CLASSIFY,
        ProcessingStage.REVIEW,
    ]
    assert statements.normalizations[0].rule_id == ("transfer_reporting_category_nullification_v1")
    assert statements.statement.status == "ready"
    assert statements.statement.current_stage == ProcessingStage.PUBLISH_STATE
    assert statements.statement.validation_result == {
        "is_valid": True,
        "calculated_closing_balance": "80.00",
        "difference": "0.00",
        "validation_version": "validation-v1",
    }
    assert statements.statement.review_findings == ()


def test_revalidate_stage_uses_effective_amounts_without_classifier() -> None:
    statement = Statement(
        id=UUID("50e5591f-913e-471b-a501-541fd860af30"),
        account_reference="BPI Main",
        original_filename="statement.pdf",
        content_hash="hash",
        source_path=Path("/tmp/statement.pdf"),
        page_count=1,
        status="processing",
        current_stage=ProcessingStage.REVALIDATE,
        extraction_result=FakeExtractor()
        .extract((ExtractedPage(number=1, text=""),))
        .model_dump(mode="json"),
    )
    statements = FakeStatements(statement)
    handlers = StatementStageHandlers(
        statements=statements,
        pdfs=FakePdfReader(),
        extractor=FakeExtractor(),
        classifier=FakeClassifier(),
    ).handlers()

    handlers[ProcessingStage.REVALIDATE](
        job(statement.id, ProcessingStage.REVALIDATE, {"correction_revision": 2})
    )

    assert statements.stages == [ProcessingStage.REVIEW]
    assert statements.statement.validation_result is not None
    assert statements.statement.validation_result["basis"] == "effective"
    assert statements.statement.validation_result["correction_revision"] == 2
