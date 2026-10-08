from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Literal, cast
from uuid import UUID

from bank_statement_assistant.statements.classification import (
    MovementKind,
    PaymentChannel,
    ReportingCategory,
    TransferScope,
)

MUTABLE_TRANSACTION_FIELDS = frozenset(
    {
        "booking_date",
        "description",
        "signed_amount",
        "currency",
        "reporting_category",
        "movement_kind",
        "payment_channel",
        "counterparty",
        "note",
        "transfer_scope",
    }
)
ClassificationResolution = Literal["pending", "accepted", "corrected"]


class ResolutionError(ValueError):
    """A correction cannot produce a valid effective transaction."""


class ResolutionConflictError(RuntimeError):
    """The caller attempted to write against a stale transaction revision."""


class ResolutionNotFoundError(LookupError):
    """The requested transaction or classification does not exist."""


@dataclass(frozen=True, slots=True)
class TransactionValues:
    booking_date: date
    description: str
    signed_amount: Decimal
    currency: str
    reporting_category: ReportingCategory | None = None
    movement_kind: MovementKind | None = None
    payment_channel: PaymentChannel | None = None
    counterparty: str | None = None
    note: str | None = None
    transfer_scope: TransferScope | None = None

    def validated(self) -> "TransactionValues":
        currency = self.currency.upper()
        if len(currency) != 3 or not currency.isalpha():
            raise ResolutionError("currency must be a three-letter ISO code")
        if not self.description.strip():
            raise ResolutionError("description must not be empty")
        if self.movement_kind is None:
            if (
                self.reporting_category is not None
                or self.payment_channel is not None
                or self.transfer_scope is not None
            ):
                raise ResolutionError("classification fields require a movement kind")
        elif self.payment_channel is None:
            raise ResolutionError("classified transactions require a payment channel")
        elif self.movement_kind == "Transfer":
            if self.reporting_category is not None:
                raise ResolutionError("transfers must not have a reporting category")
        elif self.transfer_scope is not None:
            raise ResolutionError("transfer scope requires a Transfer movement kind")
        elif self.reporting_category is None:
            raise ResolutionError("non-transfer classifications require a reporting category")
        return TransactionValues(
            booking_date=self.booking_date,
            description=self.description.strip(),
            signed_amount=self.signed_amount,
            currency=currency,
            reporting_category=self.reporting_category,
            movement_kind=self.movement_kind,
            payment_channel=self.payment_channel,
            counterparty=self.counterparty.strip() if self.counterparty else None,
            note=self.note.strip() if self.note else None,
            transfer_scope=self.transfer_scope,
        )


@dataclass(frozen=True, slots=True)
class TransactionCorrection:
    revision: int
    previous_revision: int
    values: TransactionValues
    reason: str
    origin: str = "user"
    classification_changed: bool = False


@dataclass(frozen=True, slots=True)
class CorrectionRecord:
    id: UUID
    transaction_id: UUID
    correction: TransactionCorrection
    reason: str
    origin: str
    created_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class ClassificationReview:
    id: int
    transaction_id: UUID
    classification_id: int
    decision: Literal["accepted", "rejected"]
    reason: str | None
    created_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class CorrectionCommand:
    expected_revision: int
    changes: Mapping[str, object]
    reason: str
    idempotency_key: str
    origin: str = "user"


@dataclass(frozen=True, slots=True)
class RevertCommand:
    expected_revision: int
    target_revision: int
    reason: str
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class ClassificationAcceptance:
    classification_id: int
    reason: str | None
    idempotency_key: str


def apply_changes(
    current: TransactionValues,
    changes: Mapping[str, object],
) -> TransactionValues:
    validate_change_fields(changes)
    if not changes:
        raise ResolutionError("correction must change at least one field")
    values = {
        "booking_date": current.booking_date,
        "description": current.description,
        "signed_amount": current.signed_amount,
        "currency": current.currency,
        "reporting_category": current.reporting_category,
        "movement_kind": current.movement_kind,
        "payment_channel": current.payment_channel,
        "counterparty": current.counterparty,
        "note": current.note,
        "transfer_scope": current.transfer_scope,
    }
    values.update(changes)
    candidate = TransactionValues(
        booking_date=cast(date, values["booking_date"]),
        description=cast(str, values["description"]),
        signed_amount=cast(Decimal, values["signed_amount"]),
        currency=cast(str, values["currency"]),
        reporting_category=cast(ReportingCategory | None, values["reporting_category"]),
        movement_kind=cast(MovementKind | None, values["movement_kind"]),
        payment_channel=cast(PaymentChannel | None, values["payment_channel"]),
        counterparty=cast(str | None, values["counterparty"]),
        note=cast(str | None, values["note"]),
        transfer_scope=cast(TransferScope | None, values["transfer_scope"]),
    )
    return candidate.validated()


def validate_change_fields(changes: Mapping[str, object]) -> None:
    unknown = set(changes) - MUTABLE_TRANSACTION_FIELDS
    if unknown:
        names = ", ".join(sorted(unknown))
        raise ResolutionError(f"unsupported correction field(s): {names}")


def correction_from_values(
    *,
    current_revision: int,
    current: TransactionValues,
    changes: Mapping[str, object],
    reason: str,
    origin: str = "user",
) -> TransactionCorrection:
    if current_revision < 0:
        raise ResolutionError("current revision must not be negative")
    if not reason.strip():
        raise ResolutionError("correction reason must not be empty")
    if origin not in {"user", "assistant_proposal"}:
        raise ResolutionError("unsupported correction origin")
    values = apply_changes(current, changes)
    return TransactionCorrection(
        revision=current_revision + 1,
        previous_revision=current_revision,
        values=values,
        reason=reason.strip(),
        origin=origin,
        classification_changed=bool(
            values.movement_kind is not None
            and any(
                getattr(current, field) != getattr(values, field)
                for field in (
                    "reporting_category",
                    "movement_kind",
                    "payment_channel",
                    "transfer_scope",
                )
            )
        ),
    )
