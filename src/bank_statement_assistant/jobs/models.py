from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

JobStatus = Literal["queued", "running", "succeeded", "failed"]


class ProcessingStage(StrEnum):
    ACCEPT = "accept"
    EXTRACT_TEXT = "extract_text"
    EXTRACT_TRANSACTIONS = "extract_transactions"
    VALIDATE = "validate"
    REVALIDATE = "revalidate"
    CLASSIFY = "classify"
    REVIEW = "review"
    PUBLISH_STATE = "publish_state"


@dataclass(frozen=True, slots=True)
class ProcessingJob:
    id: UUID
    statement_id: UUID
    stage: ProcessingStage
    payload: dict[str, Any]
    status: JobStatus
    priority: int
    attempts: int
    available_at: datetime
    claimed_at: datetime | None
    claimed_by: str | None
    lease_expires_at: datetime | None
    last_error_code: str | None = None
