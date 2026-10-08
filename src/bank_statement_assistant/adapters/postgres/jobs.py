import json
from collections.abc import Mapping
from datetime import timedelta
from typing import Any, cast
from uuid import UUID

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import RowMapping

from bank_statement_assistant.jobs.models import JobStatus, ProcessingJob, ProcessingStage
from bank_statement_assistant.jobs.retry import RetryPolicy


class JobOwnershipError(RuntimeError):
    """The requested job is not running under the supplied worker claim."""


class PostgresJobQueue:
    """PostgreSQL-backed queue using row locks and expiring worker leases."""

    def __init__(
        self,
        database_url: str,
        *,
        retry_delay_seconds: float = 5,
        max_attempts: int = 3,
        lease_seconds: int = 300,
    ) -> None:
        if lease_seconds < 0:
            raise ValueError("lease_seconds must not be negative")
        self._engine: Engine = create_engine(
            database_url,
            pool_pre_ping=True,
            connect_args={"connect_timeout": 5, "options": "-c statement_timeout=5000"},
        )
        self._retry_policy = RetryPolicy(
            max_attempts=max_attempts,
            base_delay=timedelta(seconds=retry_delay_seconds),
        )
        self._lease_seconds = lease_seconds

    def enqueue(
        self,
        *,
        statement_id: UUID,
        stage: ProcessingStage,
        priority: int = 0,
        payload: Mapping[str, Any] | None = None,
    ) -> ProcessingJob:
        query = text(
            """
            INSERT INTO processing_jobs (statement_id, stage, priority, payload)
            VALUES (:statement_id, :stage, :priority, CAST(:payload AS jsonb))
            RETURNING *
            """
        )
        with self._engine.begin() as connection:
            row = (
                connection.execute(
                    query,
                    {
                        "statement_id": statement_id,
                        "stage": stage.value,
                        "priority": priority,
                        "payload": json.dumps(dict(payload or {})),
                    },
                )
                .mappings()
                .one()
            )
        return _processing_job(row)

    def claim_next(self, *, worker_id: str) -> ProcessingJob | None:
        expired_claims_query = text(
            """
            SELECT id, statement_id, attempts
            FROM processing_jobs
            WHERE status = 'running' AND lease_expires_at <= now()
            ORDER BY lease_expires_at, id
            FOR UPDATE SKIP LOCKED
            LIMIT 100
            """
        )
        release_expired_claim_query = text(
            """
            UPDATE processing_jobs
            SET status = :status,
                available_at = CASE
                    WHEN :will_retry THEN now() + make_interval(secs => :retry_delay_seconds)
                    ELSE available_at
                END,
                claimed_at = NULL,
                claimed_by = NULL,
                lease_expires_at = NULL,
                last_error_code = 'lease_expired',
                updated_at = now()
            WHERE id = :job_id AND status = 'running'
            """
        )
        fail_statement_query = text(
            """
            UPDATE statements
            SET status = 'failed', last_error_code = 'lease_expired', updated_at = now()
            WHERE id = :statement_id
            """
        )
        claim_query = text(
            """
            WITH next_job AS (
                SELECT id
                FROM processing_jobs
                WHERE status = 'queued' AND available_at <= now()
                ORDER BY priority DESC, created_at, id
                FOR UPDATE SKIP LOCKED
                LIMIT 1
            )
            UPDATE processing_jobs AS job
            SET status = 'running',
                claimed_at = now(),
                claimed_by = :worker_id,
                lease_expires_at = now() + make_interval(secs => :lease_seconds),
                attempts = attempts + 1,
                updated_at = now()
            FROM next_job
            WHERE job.id = next_job.id
            RETURNING job.*
            """
        )
        with self._engine.begin() as connection:
            expired_claims = connection.execute(expired_claims_query).mappings().all()
            for expired_claim in expired_claims:
                delay = self._retry_policy.delay_after(attempt=cast(int, expired_claim["attempts"]))
                will_retry = delay is not None
                connection.execute(
                    release_expired_claim_query,
                    {
                        "job_id": expired_claim["id"],
                        "status": "queued" if will_retry else "failed",
                        "will_retry": will_retry,
                        "retry_delay_seconds": 0 if delay is None else delay.total_seconds(),
                    },
                )
                if not will_retry:
                    connection.execute(
                        fail_statement_query,
                        {"statement_id": expired_claim["statement_id"]},
                    )
            row = (
                connection.execute(
                    claim_query,
                    {
                        "worker_id": worker_id,
                        "lease_seconds": self._lease_seconds,
                    },
                )
                .mappings()
                .one_or_none()
            )
        return None if row is None else _processing_job(row)

    def complete(self, *, job_id: UUID, worker_id: str) -> ProcessingJob:
        query = text(
            """
            UPDATE processing_jobs
            SET status = 'succeeded', lease_expires_at = NULL, updated_at = now()
            WHERE id = :job_id AND status = 'running' AND claimed_by = :worker_id
            RETURNING *
            """
        )
        with self._engine.begin() as connection:
            row = (
                connection.execute(
                    query,
                    {"job_id": job_id, "worker_id": worker_id},
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            raise JobOwnershipError(f"worker {worker_id!r} does not own running job {job_id}")
        return _processing_job(row)

    def fail(
        self,
        *,
        job_id: UUID,
        worker_id: str,
        error_code: str,
        retryable: bool,
    ) -> ProcessingJob:
        ownership_query = text(
            """
            SELECT attempts
            FROM processing_jobs
            WHERE id = :job_id AND status = 'running' AND claimed_by = :worker_id
            FOR UPDATE
            """
        )
        update_query = text(
            """
            UPDATE processing_jobs
            SET status = :status,
                available_at = CASE
                    WHEN :will_retry THEN now() + make_interval(secs => :retry_delay_seconds)
                    ELSE available_at
                END,
                claimed_at = NULL,
                claimed_by = NULL,
                lease_expires_at = NULL,
                last_error_code = :error_code,
                updated_at = now()
            WHERE id = :job_id AND status = 'running' AND claimed_by = :worker_id
            RETURNING *
            """
        )
        with self._engine.begin() as connection:
            ownership = (
                connection.execute(
                    ownership_query,
                    {"job_id": job_id, "worker_id": worker_id},
                )
                .mappings()
                .one_or_none()
            )
            if ownership is None:
                raise JobOwnershipError(f"worker {worker_id!r} does not own running job {job_id}")
            delay = self._retry_policy.delay_after(attempt=cast(int, ownership["attempts"]))
            will_retry = retryable and delay is not None
            row = (
                connection.execute(
                    update_query,
                    {
                        "job_id": job_id,
                        "worker_id": worker_id,
                        "error_code": error_code,
                        "status": "queued" if will_retry else "failed",
                        "will_retry": will_retry,
                        "retry_delay_seconds": 0 if delay is None else delay.total_seconds(),
                    },
                )
                .mappings()
                .one()
            )
        return _processing_job(row)


def _processing_job(row: RowMapping) -> ProcessingJob:
    return ProcessingJob(
        id=cast(UUID, row["id"]),
        statement_id=cast(UUID, row["statement_id"]),
        stage=ProcessingStage(cast(str, row["stage"])),
        payload=cast(dict[str, Any], row["payload"]),
        status=cast(JobStatus, row["status"]),
        priority=cast(int, row["priority"]),
        attempts=cast(int, row["attempts"]),
        available_at=row["available_at"],
        claimed_at=row["claimed_at"],
        claimed_by=cast(str | None, row["claimed_by"]),
        lease_expires_at=row["lease_expires_at"],
        last_error_code=cast(str | None, row["last_error_code"]),
    )
