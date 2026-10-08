import os
import time
from collections.abc import Iterator
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, text

from bank_statement_assistant.adapters.postgres.jobs import JobOwnershipError, PostgresJobQueue
from bank_statement_assistant.jobs.models import ProcessingStage


@pytest.fixture
def database_url() -> str:
    value = os.getenv("TEST_DATABASE_URL")
    if value is None:
        pytest.skip("TEST_DATABASE_URL is not configured")
    return value


@pytest.fixture
def clean_database(database_url: str) -> Iterator[None]:
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


def create_statement(database_url: str, statement_id: UUID) -> None:
    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO statements (
                    id, account_reference, original_filename, content_hash,
                    source_path, page_count, status, current_stage
                ) VALUES (
                    :id, 'Test', :filename, :content_hash,
                    :source_path, 1, 'processing', 'extract_text'
                )
                """
            ),
            {
                "id": statement_id,
                "filename": f"{statement_id}.pdf",
                "content_hash": str(statement_id),
                "source_path": f"/tmp/{statement_id}.pdf",
            },
        )
    engine.dispose()


@pytest.mark.postgres
def test_claim_next_is_atomic_and_honours_priority(
    database_url: str,
    clean_database: None,
) -> None:
    queue_a = PostgresJobQueue(database_url)
    queue_b = PostgresJobQueue(database_url)
    low_priority_statement = uuid4()
    high_priority_statement = uuid4()
    create_statement(database_url, low_priority_statement)
    create_statement(database_url, high_priority_statement)
    queue_a.enqueue(
        statement_id=low_priority_statement,
        stage=ProcessingStage.EXTRACT_TEXT,
        priority=1,
    )
    queue_a.enqueue(
        statement_id=high_priority_statement,
        stage=ProcessingStage.EXTRACT_TEXT,
        priority=10,
    )

    first = queue_a.claim_next(worker_id="worker-a")
    second = queue_b.claim_next(worker_id="worker-b")

    assert first is not None
    assert first.statement_id == high_priority_statement
    assert first.status == "running"
    assert first.claimed_by == "worker-a"
    assert second is not None
    assert second.statement_id == low_priority_statement
    assert second.claimed_by == "worker-b"
    assert queue_b.claim_next(worker_id="worker-b") is None


@pytest.mark.postgres
def test_only_the_claiming_worker_can_complete_a_job(
    database_url: str,
    clean_database: None,
) -> None:
    queue = PostgresJobQueue(database_url)
    statement_id = uuid4()
    create_statement(database_url, statement_id)
    queued = queue.enqueue(statement_id=statement_id, stage=ProcessingStage.EXTRACT_TEXT)
    claimed = queue.claim_next(worker_id="worker-a")
    assert claimed is not None

    with pytest.raises(JobOwnershipError):
        queue.complete(job_id=queued.id, worker_id="worker-b")

    completed = queue.complete(job_id=queued.id, worker_id="worker-a")
    assert completed.status == "succeeded"


@pytest.mark.postgres
def test_retryable_failures_are_requeued_until_the_attempt_limit(
    database_url: str,
    clean_database: None,
) -> None:
    queue = PostgresJobQueue(database_url, retry_delay_seconds=0, max_attempts=2)
    statement_id = uuid4()
    create_statement(database_url, statement_id)
    queued = queue.enqueue(statement_id=statement_id, stage=ProcessingStage.EXTRACT_TEXT)
    first_claim = queue.claim_next(worker_id="worker-a")
    assert first_claim is not None

    retry = queue.fail(
        job_id=queued.id,
        worker_id="worker-a",
        error_code="model_unavailable",
        retryable=True,
    )
    assert retry.status == "queued"
    second_claim = queue.claim_next(worker_id="worker-b")
    assert second_claim is not None

    failed = queue.fail(
        job_id=queued.id,
        worker_id="worker-b",
        error_code="model_unavailable",
        retryable=True,
    )
    assert failed.status == "failed"
    assert failed.last_error_code == "model_unavailable"


@pytest.mark.postgres
def test_an_expired_worker_claim_can_be_recovered(
    database_url: str,
    clean_database: None,
) -> None:
    queue = PostgresJobQueue(
        database_url,
        lease_seconds=0,
        retry_delay_seconds=0.05,
    )
    statement_id = uuid4()
    create_statement(database_url, statement_id)
    queued = queue.enqueue(statement_id=statement_id, stage=ProcessingStage.EXTRACT_TEXT)

    first_claim = queue.claim_next(worker_id="worker-a")

    assert first_claim is not None
    assert queue.claim_next(worker_id="worker-b") is None

    time.sleep(0.08)
    recovered_claim = queue.claim_next(worker_id="worker-b")
    assert recovered_claim is not None
    assert recovered_claim.id == queued.id
    assert recovered_claim.claimed_by == "worker-b"
    assert recovered_claim.attempts == 2

    assert queue.claim_next(worker_id="worker-c") is None

    time.sleep(0.12)
    final_claim = queue.claim_next(worker_id="worker-c")
    assert final_claim is not None
    assert final_claim.attempts == 3
    assert queue.claim_next(worker_id="worker-d") is None
    engine = create_engine(database_url)
    with engine.connect() as connection:
        status_and_error = connection.execute(
            text("SELECT status, last_error_code FROM statements WHERE id = :id"),
            {"id": statement_id},
        ).one()
    engine.dispose()
    assert status_and_error == ("failed", "lease_expired")
