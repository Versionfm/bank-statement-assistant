import os
from collections.abc import Iterator
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import create_engine, text

from bank_statement_assistant.adapters.postgres.statements import PostgresStatementRepository
from bank_statement_assistant.jobs.models import ProcessingStage
from bank_statement_assistant.statements.classification import (
    TRANSFER_REPORTING_CATEGORY_RULE,
    ClassificationDecision,
    ClassificationNormalization,
)
from bank_statement_assistant.statements.models import ExtractedPage, Statement
from bank_statement_assistant.statements.transactions import TransactionFilters


@pytest.fixture
def database_url() -> str:
    value = os.getenv("TEST_DATABASE_URL")
    if value is None:
        pytest.skip("TEST_DATABASE_URL is not configured")
    return value


@pytest.fixture
def clean_statements(database_url: str) -> Iterator[None]:
    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(
            text(
                "TRUNCATE transaction_classification_reviews, transaction_corrections, "
                "statement_validation_runs, review_findings, transactions, "
                "processing_jobs, statements"
            )
        )
    yield
    with engine.begin() as connection:
        connection.execute(
            text(
                "TRUNCATE transaction_classification_reviews, transaction_corrections, "
                "statement_validation_runs, review_findings, transactions, "
                "processing_jobs, statements"
            )
        )
    engine.dispose()


def processing_job_id(database_url: str, statement_id: UUID, stage: str) -> UUID:
    engine = create_engine(database_url)
    with engine.connect() as connection:
        value = connection.execute(
            text(
                """
                SELECT id FROM processing_jobs
                WHERE statement_id = :statement_id AND stage = :stage
                ORDER BY created_at DESC LIMIT 1
                """
            ),
            {"statement_id": statement_id, "stage": stage},
        ).scalar_one()
    engine.dispose()
    assert isinstance(value, UUID)
    return value


@pytest.mark.postgres
def test_repository_preserves_source_extraction_validation_and_review_state(
    database_url: str,
    clean_statements: None,
) -> None:
    repository = PostgresStatementRepository(database_url)
    statement = Statement(
        id=UUID("50e5591f-913e-471b-a501-541fd860af30"),
        account_reference="BPI Main",
        original_filename="statement.pdf",
        content_hash="57a9a89b0ccad1e6",
        source_path=Path("/private/statement.pdf"),
        page_count=1,
        status="processing",
        current_stage=ProcessingStage.EXTRACT_TEXT,
    )

    created = repository.create_with_job(
        statement=statement,
        stage=ProcessingStage.EXTRACT_TEXT,
        payload={"source_path": str(statement.source_path)},
    )
    extract_text_job_id = processing_job_id(database_url, statement.id, "extract_text")
    extracted = repository.save_extracted_pages_and_enqueue(
        statement_id=statement.id,
        pages=(
            ExtractedPage(
                number=1,
                text="2026-08-02 Groceries -20.00 EUR\nOpening 100, closing 80",
            ),
        ),
        predecessor_job_id=extract_text_job_id,
        next_stage=ProcessingStage.EXTRACT_TRANSACTIONS,
    )
    extract_transactions_job_id = processing_job_id(
        database_url, statement.id, "extract_transactions"
    )
    repository.save_extraction_and_enqueue(
        statement_id=statement.id,
        result={
            "opening_balance": "100.00",
            "closing_balance": "80.00",
            "transactions": [
                {
                    "booking_date": "2026-08-02",
                    "description": "Groceries",
                    "signed_amount": "-20.00",
                    "currency": "EUR",
                    "evidence_page_number": 1,
                    "evidence_line_start": 1,
                    "evidence_line_end": 1,
                    "evidence_quote": "2026-08-02 Groceries -20.00 EUR",
                    "confidence": 0.99,
                }
            ],
        },
        predecessor_job_id=extract_transactions_job_id,
        next_stage=ProcessingStage.VALIDATE,
    )
    validate_job_id = processing_job_id(database_url, statement.id, "validate")
    repository.save_validation_and_enqueue(
        statement_id=statement.id,
        result={"is_valid": False, "difference": "0.00"},
        findings=[
            {
                "code": "balance_mismatch",
                "message": "Review required.",
                "transaction_index": 0,
            },
            {"code": "statement_issue", "message": "Statement review required."},
        ],
        predecessor_job_id=validate_job_id,
        next_stage=ProcessingStage.REVIEW,
    )
    published = repository.publish_status(statement_id=statement.id, ready=False)
    transactions = repository.list_transactions(
        filters=TransactionFilters(statement_id=statement.id, review_only=True)
    )

    assert created.created_at is not None
    assert extracted.extracted_pages[0].number == 1
    assert repository.find_by_content_hash(statement.content_hash) is not None
    assert repository.list()[0].id == statement.id
    assert transactions.total == 1
    assert transactions.items[0].evidence_line_start == 1
    assert transactions.items[0].evidence_quote == "2026-08-02 Groceries -20.00 EUR"
    assert transactions.items[0].review_findings == (
        {"code": "balance_mismatch", "message": "Review required."},
        {"code": "statement_issue", "message": "Statement review required."},
    )
    assert published.status == "needs_review"
    assert published.current_stage == ProcessingStage.PUBLISH_STATE
    assert published.validation_result == {"is_valid": False, "difference": "0.00"}
    repository.mark_failed(statement_id=statement.id, error_code="validate_failed")
    restarted = repository.restart_with_job(statement_id=statement.id)
    assert restarted.status == "processing"
    engine = create_engine(database_url)
    with engine.connect() as connection:
        jobs = connection.execute(
            text("SELECT count(*) FROM processing_jobs WHERE statement_id = :id"),
            {"id": statement.id},
        ).scalar_one()
    engine.dispose()
    assert jobs == 5


@pytest.mark.postgres
def test_stage_transition_is_atomic_and_idempotent(
    database_url: str,
    clean_statements: None,
) -> None:
    repository = PostgresStatementRepository(database_url)
    statement = Statement(
        id=UUID("3ca2ae47-7bbd-4dc7-a8cc-cc95f0a2629b"),
        account_reference="BPI Main",
        original_filename="statement.pdf",
        content_hash="atomic-hash",
        source_path=Path("/private/atomic.pdf"),
        page_count=1,
        status="processing",
        current_stage=ProcessingStage.EXTRACT_TEXT,
    )
    repository.create_with_job(
        statement=statement,
        stage=ProcessingStage.EXTRACT_TEXT,
        payload={},
    )
    predecessor_job_id = processing_job_id(database_url, statement.id, "extract_text")

    for _ in range(2):
        repository.save_extracted_pages_and_enqueue(
            statement_id=statement.id,
            pages=(ExtractedPage(number=1, text="Synthetic"),),
            predecessor_job_id=predecessor_job_id,
            next_stage=ProcessingStage.EXTRACT_TRANSACTIONS,
        )

    engine = create_engine(database_url)
    with engine.connect() as connection:
        successor_count = connection.execute(
            text(
                """
                SELECT count(*) FROM processing_jobs
                WHERE predecessor_job_id = :predecessor_job_id
                """
            ),
            {"predecessor_job_id": predecessor_job_id},
        ).scalar_one()
    engine.dispose()
    assert successor_count == 1


@pytest.mark.postgres
def test_retry_requeues_a_failed_classification_stage(
    database_url: str,
    clean_statements: None,
) -> None:
    repository = PostgresStatementRepository(database_url)
    statement = Statement(
        id=UUID("f9bfe52e-8ff2-4d0d-96ac-b5e03e246ea5"),
        account_reference="BPI Main",
        original_filename="failed-classification.pdf",
        content_hash="failed-classification-hash",
        source_path=Path("/private/failed-classification.pdf"),
        page_count=1,
        status="failed",
        current_stage=ProcessingStage.CLASSIFY,
        last_error_code="classify_invalid_response",
    )
    repository.create_with_job(
        statement=replace(statement, status="processing"),
        stage=ProcessingStage.CLASSIFY,
        payload={},
    )
    repository.mark_failed(statement_id=statement.id, error_code=statement.last_error_code)

    restarted = repository.restart_with_job(statement_id=statement.id)

    assert restarted.status == "processing"
    assert restarted.current_stage == ProcessingStage.CLASSIFY
    engine = create_engine(database_url)
    with engine.connect() as connection:
        latest_job = connection.execute(
            text(
                """
                SELECT stage, status
                FROM processing_jobs
                WHERE statement_id = :statement_id
                ORDER BY created_at DESC
                LIMIT 1
                """
            ),
            {"statement_id": statement.id},
        ).one()
    engine.dispose()
    assert latest_job == ("classify", "queued")


@pytest.mark.postgres
def test_valid_validation_enqueues_classification_stage(
    database_url: str,
    clean_statements: None,
) -> None:
    repository = PostgresStatementRepository(database_url)
    statement = Statement(
        id=UUID("e9aa4a9a-3ef4-4e7e-9c34-2a82d0ab1d6a"),
        account_reference="BPI Main",
        original_filename="classification.pdf",
        content_hash="classification-hash",
        source_path=Path("/private/classification.pdf"),
        page_count=1,
        status="processing",
        current_stage=ProcessingStage.EXTRACT_TEXT,
    )
    repository.create_with_job(
        statement=statement,
        stage=ProcessingStage.EXTRACT_TEXT,
        payload={},
    )
    extract_text_job_id = processing_job_id(database_url, statement.id, "extract_text")
    repository.save_extracted_pages_and_enqueue(
        statement_id=statement.id,
        pages=(ExtractedPage(number=1, text="Synthetic"),),
        predecessor_job_id=extract_text_job_id,
        next_stage=ProcessingStage.EXTRACT_TRANSACTIONS,
    )
    extract_transactions_job_id = processing_job_id(
        database_url, statement.id, "extract_transactions"
    )
    repository.save_extraction_and_enqueue(
        statement_id=statement.id,
        result={
            "transactions": [
                {
                    "booking_date": "2026-08-02",
                    "description": "Groceries",
                    "signed_amount": "-20.00",
                    "currency": "EUR",
                    "evidence_page_number": 1,
                    "evidence_line_start": 1,
                    "evidence_line_end": 1,
                    "evidence_quote": "Synthetic",
                    "confidence": 0.99,
                }
            ]
        },
        predecessor_job_id=extract_transactions_job_id,
        next_stage=ProcessingStage.VALIDATE,
    )
    validate_job_id = processing_job_id(database_url, statement.id, "validate")

    classified = repository.save_validation_and_enqueue(
        statement_id=statement.id,
        result={"is_valid": True},
        findings=[],
        predecessor_job_id=validate_job_id,
        next_stage=ProcessingStage.CLASSIFY,
    )

    assert classified.current_stage == ProcessingStage.CLASSIFY
    classify_job_id = processing_job_id(database_url, statement.id, "classify")
    first_decision = ClassificationDecision(
        source_ordinal=1,
        reporting_category=None,
        movement_kind="Transfer",
        payment_channel="Bank Transfer",
        confidence=0.95,
        rationale="First transfer decision",
    )
    repository.save_classifications_and_enqueue(
        statement_id=statement.id,
        decisions=(first_decision,),
        normalizations=(
            ClassificationNormalization(
                source_ordinal=1,
                rule_id=TRANSFER_REPORTING_CATEGORY_RULE,
            ),
        ),
        provenance={"model": "test-model", "prompt_version": "test-v1"},
        predecessor_job_id=classify_job_id,
        next_stage=ProcessingStage.REVIEW,
    )
    second_decision = first_decision.model_copy(
        update={
            "reporting_category": "Restaurants & Cafes",
            "movement_kind": "Expense",
            "payment_channel": "Card",
            "confidence": 0.5,
            "rationale": "Second model decision",
        }
    )
    repository.save_classifications_and_enqueue(
        statement_id=statement.id,
        decisions=(second_decision,),
        provenance={"model": "test-model", "prompt_version": "test-v2"},
        predecessor_job_id=classify_job_id,
        next_stage=ProcessingStage.REVIEW,
    )
    engine = create_engine(database_url)
    with engine.connect() as connection:
        next_stage = connection.execute(
            text(
                """
                SELECT stage FROM processing_jobs
                WHERE predecessor_job_id = :predecessor_job_id
                """
            ),
            {"predecessor_job_id": validate_job_id},
        ).scalar_one()
        classification_count = connection.execute(
            text(
                """
                SELECT count(*) FROM transaction_classifications AS tc
                JOIN transactions AS t ON t.id = tc.transaction_id
                WHERE t.statement_id = :statement_id
                """
            ),
            {"statement_id": statement.id},
        ).scalar_one()
        normalization_rules = connection.execute(
            text(
                """
                SELECT classification_provenance->'normalization_rules'
                FROM transaction_classifications
                WHERE transaction_id = (
                    SELECT id FROM transactions WHERE statement_id = :statement_id
                )
                ORDER BY id
                LIMIT 1
                """
            ),
            {"statement_id": statement.id},
        ).scalar_one()
    engine.dispose()
    assert next_stage == "classify"
    assert classification_count == 2
    assert normalization_rules == [TRANSFER_REPORTING_CATEGORY_RULE]
    latest = repository.list_transactions(
        filters=TransactionFilters(statement_id=statement.id)
    ).items[0]
    assert latest.reporting_category == "Restaurants & Cafes"
    assert latest.classification_status == "needs_review"
    assert repository.all_transactions_classified(statement_id=statement.id) is False

    filtered = repository.list_transactions(
        filters=TransactionFilters(
            statement_id=statement.id,
            description_query="grocer",
            amount_min=Decimal("20.00"),
            amount_max=Decimal("20.00"),
            movement_kind="Expense",
            money_direction="out",
            classification_status="needs_review",
            payment_channel="Card",
            reporting_category="Restaurants & Cafes",
            currency="eur",
        )
    )
    assert filtered.total == 1
    assert filtered.items[0].description == "Groceries"
    assert (
        repository.list_transactions(
            filters=TransactionFilters(statement_id=statement.id, amount_min=Decimal("20.01"))
        ).total
        == 0
    )
