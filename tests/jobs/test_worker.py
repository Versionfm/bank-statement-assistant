from dataclasses import replace
from datetime import UTC, datetime
from time import sleep
from typing import Any
from uuid import uuid4

from bank_statement_assistant.jobs.models import ProcessingJob, ProcessingStage
from bank_statement_assistant.jobs.worker import Worker


class RecordingQueue:
    def __init__(self, job: ProcessingJob | None) -> None:
        self.job = job
        self.claim_count = 0
        self.completed: list[tuple[object, str]] = []
        self.failed: list[dict[str, Any]] = []

    def claim_next(self, *, worker_id: str) -> ProcessingJob | None:
        self.claim_count += 1
        return self.job

    def complete(self, *, job_id: object, worker_id: str) -> ProcessingJob:
        self.completed.append((job_id, worker_id))
        assert self.job is not None
        return self.job

    def fail(self, **kwargs: Any) -> ProcessingJob:
        self.failed.append(kwargs)
        assert self.job is not None
        return self.job


def a_job(stage: ProcessingStage = ProcessingStage.EXTRACT_TEXT) -> ProcessingJob:
    now = datetime.now(UTC)
    return ProcessingJob(
        id=uuid4(),
        statement_id=uuid4(),
        stage=stage,
        payload={},
        status="running",
        priority=0,
        attempts=1,
        available_at=now,
        claimed_at=now,
        claimed_by="worker-a",
        lease_expires_at=now,
    )


def test_worker_completes_a_successful_stage() -> None:
    job = a_job()
    queue = RecordingQueue(job)
    handled: list[ProcessingJob] = []
    worker = Worker(
        queue=queue,
        worker_id="worker-a",
        handlers={ProcessingStage.EXTRACT_TEXT: handled.append},
    )

    assert worker.process_next() is True
    assert handled == [job]
    assert queue.completed == [(job.id, "worker-a")]
    assert queue.failed == []


def test_worker_requeues_a_stage_after_an_unexpected_failure() -> None:
    job = a_job()
    queue = RecordingQueue(job)

    def fail(_job: ProcessingJob) -> None:
        raise RuntimeError("sensitive details")

    worker = Worker(
        queue=queue,
        worker_id="worker-a",
        handlers={ProcessingStage.EXTRACT_TEXT: fail},
    )

    assert worker.process_next() is True
    assert queue.failed == [
        {
            "job_id": job.id,
            "worker_id": "worker-a",
            "error_code": "stage_failed",
            "retryable": True,
        }
    ]


def test_worker_preserves_a_safe_stage_error_code() -> None:
    job = a_job(ProcessingStage.CLASSIFY)
    queue = RecordingQueue(job)

    class ClassificationFailure(RuntimeError):
        error_code = "classify_invalid_response"

    def fail(_job: ProcessingJob) -> None:
        raise ClassificationFailure("response details must not escape")

    worker = Worker(
        queue=queue,
        worker_id="worker-a",
        handlers={ProcessingStage.CLASSIFY: fail},
    )

    assert worker.process_next() is True
    assert queue.failed[0]["error_code"] == "classify_invalid_response"


def test_worker_reports_a_terminal_failure_for_visible_statement_state() -> None:
    failed_job = a_job()
    failed_job = replace(failed_job, status="failed")
    queue = RecordingQueue(a_job())
    queue.fail = lambda **kwargs: failed_job  # type: ignore[method-assign]
    observed: list[tuple[ProcessingJob, ProcessingJob]] = []

    def fail(_job: ProcessingJob) -> None:
        raise RuntimeError("boom")

    worker = Worker(
        queue=queue,
        worker_id="worker-a",
        handlers={ProcessingStage.EXTRACT_TEXT: fail},
        failure_observer=lambda original, result: observed.append((original, result)),
    )

    worker.process_next()

    assert observed == [(queue.job, failed_job)]


def test_worker_bounds_stage_execution_time() -> None:
    job = a_job()
    queue = RecordingQueue(job)

    def hang(_job: ProcessingJob) -> None:
        sleep(1)

    worker = Worker(
        queue=queue,
        worker_id="worker-a",
        handlers={ProcessingStage.EXTRACT_TEXT: hang},
        handler_timeout_seconds=0.01,
    )

    assert worker.process_next() is True
    assert queue.failed[0]["error_code"] == "stage_timeout"


def test_worker_does_not_claim_work_before_the_schema_is_ready() -> None:
    queue = RecordingQueue(a_job())
    worker = Worker(
        queue=queue,
        worker_id="worker-a",
        handlers={},
        readiness=lambda: False,
    )

    assert worker.process_next() is False
    assert queue.claim_count == 0
