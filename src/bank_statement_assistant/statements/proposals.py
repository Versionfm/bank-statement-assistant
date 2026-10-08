"""Non-binding correction proposals created by assistant adapters."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from bank_statement_assistant.statements.resolution import ResolutionConflictError
from bank_statement_assistant.statements.transactions import Transaction


@dataclass(frozen=True, slots=True)
class CorrectionProposal:
    id: UUID
    transaction_id: UUID
    expected_revision: int
    before_values: dict[str, object]
    proposed_changes: dict[str, object]
    reason: str
    evidence: tuple[dict[str, str], ...]
    model: str
    prompt_version: str
    status: str
    idempotency_key: str
    created_at: datetime | None = None


class CorrectionProposalRepository(Protocol):
    def create(
        self,
        *,
        transaction: Transaction,
        expected_revision: int,
        changes: Mapping[str, object],
        reason: str,
        evidence: tuple[dict[str, str], ...],
        model: str,
        prompt_version: str,
        idempotency_key: str,
    ) -> CorrectionProposal: ...


def proposal_before_values(transaction: Transaction) -> dict[str, object]:
    return {
        "booking_date": transaction.booking_date.isoformat(),
        "description": transaction.description,
        "signed_amount": str(transaction.signed_amount),
        "currency": transaction.currency,
        "reporting_category": transaction.reporting_category,
        "movement_kind": transaction.movement_kind,
        "payment_channel": transaction.payment_channel,
        "counterparty": transaction.counterparty,
        "note": transaction.note,
        "transfer_scope": transaction.transfer_scope,
    }


def ensure_current_revision(transaction: Transaction, expected_revision: int) -> None:
    if expected_revision != transaction.correction_revision:
        raise ResolutionConflictError(
            f"transaction revision is {transaction.correction_revision}, not {expected_revision}"
        )
