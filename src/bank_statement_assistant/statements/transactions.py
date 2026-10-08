from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Literal, Protocol
from uuid import UUID

from bank_statement_assistant.statements.classification import (
    ClassificationStatus,
    MovementKind,
    PaymentChannel,
    ReportingCategory,
    TransferScope,
)
from bank_statement_assistant.statements.models import StatementStatus
from bank_statement_assistant.statements.resolution import (
    ClassificationAcceptance,
    ClassificationResolution,
    CorrectionCommand,
    CorrectionRecord,
    RevertCommand,
    TransactionValues,
)

TransactionSort = Literal["booking_date", "signed_amount", "description", "source_ordinal"]


@dataclass(frozen=True, slots=True)
class Transaction:
    id: UUID
    statement_id: UUID
    statement_filename: str
    statement_status: StatementStatus
    source_ordinal: int
    booking_date: date
    description: str
    signed_amount: Decimal
    currency: str
    confidence: float
    evidence_page_number: int | None
    evidence_line_start: int | None
    evidence_line_end: int | None
    evidence_quote: str | None
    reporting_category: ReportingCategory | None = None
    movement_kind: MovementKind | None = None
    payment_channel: PaymentChannel | None = None
    transfer_scope: TransferScope | None = None
    counterparty: str | None = None
    note: str | None = None
    classification_status: ClassificationStatus = "unclassified"
    classification_confidence: float | None = None
    classification_provenance: dict[str, object] | None = None
    review_findings: tuple[dict[str, str], ...] = ()
    created_at: datetime | None = None
    classification_id: int | None = None
    classification_resolution: ClassificationResolution = "pending"
    correction_revision: int = 0
    original_values: TransactionValues | None = None


@dataclass(frozen=True, slots=True)
class TransactionFilters:
    statement_id: UUID | None = None
    review_only: bool = False
    booking_date_from: date | None = None
    booking_date_to: date | None = None
    description_query: str | None = None
    amount_min: Decimal | None = None
    amount_max: Decimal | None = None
    movement_kind: MovementKind | None = None
    money_direction: Literal["in", "out"] | None = None
    classification_status: ClassificationStatus | None = None
    payment_channel: PaymentChannel | None = None
    transfer_scope: TransferScope | None = None
    reporting_category: ReportingCategory | None = None
    currency: str | None = None
    sort: TransactionSort = "booking_date"
    descending: bool = True
    limit: int = 50
    offset: int = 0

    def __post_init__(self) -> None:
        if self.amount_min is not None and self.amount_min < 0:
            raise ValueError("amount_min must not be negative")
        if self.amount_max is not None and self.amount_max < 0:
            raise ValueError("amount_max must not be negative")
        if (
            self.amount_min is not None
            and self.amount_max is not None
            and self.amount_min > self.amount_max
        ):
            raise ValueError("amount_min must not be greater than amount_max")


@dataclass(frozen=True, slots=True)
class TransactionPage:
    items: tuple[Transaction, ...]
    total: int
    limit: int
    offset: int


class TransactionRepository(Protocol):
    def list(self, *, filters: TransactionFilters) -> TransactionPage: ...

    def get(self, transaction_id: UUID) -> Transaction | None: ...

    def correct(self, transaction_id: UUID, command: CorrectionCommand) -> Transaction: ...

    def history(self, transaction_id: UUID) -> tuple[CorrectionRecord, ...]: ...

    def revert(self, transaction_id: UUID, command: RevertCommand) -> Transaction: ...

    def accept_classification(
        self, transaction_id: UUID, acceptance: ClassificationAcceptance
    ) -> Transaction: ...
