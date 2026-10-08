import logging
import re
import signal
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from typing import Protocol
from uuid import UUID

from bank_statement_assistant.jobs.models import ProcessingJob, ProcessingStage

JobHandler = Callable[[ProcessingJob], None]


class StageTimeoutError(TimeoutError):
    """A stage exceeded the worker's bounded execution window."""


@contextmanager
def _handler_deadline(seconds: float) -> Iterator[None]:
    def raise_timeout(_signum: int, _frame: object) -> None:
        raise StageTimeoutError

    previous_handler = signal.signal(signal.SIGALRM, raise_timeout)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)


class JobQueue(Protocol):
    def claim_next(self, *, worker_id: str) -> ProcessingJob | None: ...

    def complete(self, *, job_id: UUID, worker_id: str) -> ProcessingJob: ...

    def fail(
        self,
        *,
        job_id: UUID,
        worker_id: str,
        error_code: str,
        retryable: bool,
    ) -> ProcessingJob: ...


class Worker:
    def __init__(
        self,
        *,
        queue: JobQueue,
        worker_id: str,
        handlers: Mapping[ProcessingStage, JobHandler],
        handler_timeout_seconds: float = 120,
        readiness: Callable[[], bool] | None = None,
        failure_observer: Callable[[ProcessingJob, ProcessingJob], None] | None = None,
    ) -> None:
        if handler_timeout_seconds <= 0:
            raise ValueError("handler_timeout_seconds must be positive")
        self._queue = queue
        self._worker_id = worker_id
        self._handlers = handlers
        self._handler_timeout_seconds = handler_timeout_seconds
        self._readiness = readiness or (lambda: True)
        self._failure_observer = failure_observer
        self._logger = logging.getLogger(__name__)

    def process_next(self) -> bool:
        if not self._readiness():
            return False
        job = self._queue.claim_next(worker_id=self._worker_id)
        if job is None:
            return False
        handler = self._handlers.get(job.stage)
        if handler is None:
            self._logger.error(
                "unknown_job_stage",
                extra={
                    "job_id": str(job.id),
                    "statement_id": str(job.statement_id),
                    "stage": job.stage.value,
                    "attempt": job.attempts,
                },
            )
            failed = self._queue.fail(
                job_id=job.id,
                worker_id=self._worker_id,
                error_code="unknown_stage",
                retryable=False,
            )
            self._observe_failure(job, failed)
            return True
        try:
            self._logger.info(
                "job_stage_started",
                extra={
                    "job_id": str(job.id),
                    "statement_id": str(job.statement_id),
                    "stage": job.stage.value,
                    "attempt": job.attempts,
                },
            )
            with _handler_deadline(self._handler_timeout_seconds):
                handler(job)
        except StageTimeoutError:
            self._logger.error(
                "job_stage_timed_out",
                extra={
                    "job_id": str(job.id),
                    "statement_id": str(job.statement_id),
                    "stage": job.stage.value,
                    "attempt": job.attempts,
                    "exception_type": StageTimeoutError.__name__,
                    "exception_message": "stage exceeded the worker deadline",
                },
            )
            failed = self._queue.fail(
                job_id=job.id,
                worker_id=self._worker_id,
                error_code="stage_timeout",
                retryable=True,
            )
            self._observe_failure(job, failed)
        except Exception as exception:
            error_code = _safe_error_code(exception, job.stage)
            self._logger.exception(
                "job_stage_failed",
                extra={
                    "job_id": str(job.id),
                    "statement_id": str(job.statement_id),
                    "stage": job.stage.value,
                    "attempt": job.attempts,
                    "error_code": error_code,
                },
            )
            failed = self._queue.fail(
                job_id=job.id,
                worker_id=self._worker_id,
                error_code=error_code,
                retryable=True,
            )
            self._observe_failure(job, failed)
        else:
            self._queue.complete(job_id=job.id, worker_id=self._worker_id)
            self._logger.info(
                "job_stage_succeeded",
                extra={
                    "job_id": str(job.id),
                    "statement_id": str(job.statement_id),
                    "stage": job.stage.value,
                    "attempt": job.attempts,
                },
            )
        return True

    def _observe_failure(self, original: ProcessingJob, result: ProcessingJob) -> None:
        if self._failure_observer is not None:
            self._failure_observer(original, result)


def _safe_error_code(exception: BaseException, stage: ProcessingStage) -> str:
    candidate = getattr(exception, "error_code", None)
    if (
        isinstance(candidate, str)
        and candidate.startswith(f"{stage.value}_")
        and re.fullmatch(r"[a-z][a-z0-9_]{0,63}", candidate) is not None
    ):
        return candidate
    return "stage_failed"
