"""PostgreSQL persistence for immutable assistant correction proposals."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal
from typing import Any, cast
from uuid import UUID

from sqlalchemy import create_engine, text

from bank_statement_assistant.statements.proposals import (
    CorrectionProposal,
    CorrectionProposalRepository,
    ensure_current_revision,
    proposal_before_values,
)
from bank_statement_assistant.statements.resolution import (
    ResolutionConflictError,
    TransactionValues,
    apply_changes,
)
from bank_statement_assistant.statements.transactions import Transaction


class PostgresCorrectionProposalRepository(CorrectionProposalRepository):
    def __init__(self, database_url: str) -> None:
        self._engine = create_engine(database_url, pool_pre_ping=True)

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
    ) -> CorrectionProposal:
        ensure_current_revision(transaction, expected_revision)
        current = TransactionValues(
            booking_date=transaction.booking_date,
            description=transaction.description,
            signed_amount=transaction.signed_amount,
            currency=transaction.currency,
            reporting_category=transaction.reporting_category,
            movement_kind=transaction.movement_kind,
            payment_channel=transaction.payment_channel,
            counterparty=transaction.counterparty,
            note=transaction.note,
            transfer_scope=transaction.transfer_scope,
        )
        apply_changes(current, changes)
        before = proposal_before_values(transaction)
        proposed = {
            key: _json_value(value)
            for key, value in changes.items()
        }
        with self._engine.begin() as connection:
            connection.execute(
                text("SELECT id FROM transactions WHERE id = :transaction_id FOR UPDATE"),
                {"transaction_id": transaction.id},
            ).one()
            current_revision = connection.execute(
                text(
                    """
                    SELECT COALESCE(MAX(revision), 0)
                    FROM transaction_corrections
                    WHERE transaction_id = :transaction_id
                    """
                ),
                {"transaction_id": transaction.id},
            ).scalar_one()
            if int(current_revision) != expected_revision:
                raise ResolutionConflictError(
                    f"transaction revision is {current_revision}, not {expected_revision}"
                )
            existing = connection.execute(
                text("SELECT * FROM transaction_correction_proposals WHERE idempotency_key = :key"),
                {"key": idempotency_key},
            ).mappings().one_or_none()
            if existing is not None:
                if existing["transaction_id"] != transaction.id:
                    raise ValueError("idempotency key belongs to another transaction")
                if (
                    int(existing["expected_revision"]) != expected_revision
                    or existing["proposed_changes"] != proposed
                    or existing["reason"] != reason.strip()
                    or existing["evidence"] != list(evidence)
                    or existing["model"] != model
                    or existing["prompt_version"] != prompt_version
                ):
                    raise ValueError("idempotency key was reused with different proposal data")
                return _proposal(cast(Mapping[str, Any], existing))
            row = connection.execute(
                text(
                    """
                    INSERT INTO transaction_correction_proposals (
                        transaction_id, expected_revision, before_values,
                        proposed_changes, reason, evidence, model, prompt_version, idempotency_key
                    ) VALUES (
                        :transaction_id, :expected_revision, CAST(:before AS jsonb),
                        CAST(:changes AS jsonb), :reason, CAST(:evidence AS jsonb),
                        :model, :prompt_version, :idempotency_key
                    )
                    RETURNING *
                    """
                ),
                {
                    "transaction_id": transaction.id,
                    "expected_revision": expected_revision,
                    "before": json.dumps(before),
                    "changes": json.dumps(proposed),
                    "reason": reason.strip(),
                    "evidence": json.dumps(list(evidence)),
                    "model": model,
                    "prompt_version": prompt_version,
                    "idempotency_key": idempotency_key,
                },
            ).mappings().one()
        return _proposal(cast(Mapping[str, Any], row))

    def dispose(self) -> None:
        self._engine.dispose()


def _json_value(value: object) -> object:
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    if isinstance(value, Decimal):
        return str(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    raise TypeError(f"proposal value is not JSON serializable: {type(value).__name__}")


def _proposal(row: Mapping[str, Any]) -> CorrectionProposal:
    before = cast(dict[str, object], row["before_values"])
    changes = cast(dict[str, object], row["proposed_changes"])
    evidence = cast(list[dict[str, str]], row["evidence"])
    return CorrectionProposal(
        id=cast(UUID, row["id"]),
        transaction_id=cast(UUID, row["transaction_id"]),
        expected_revision=int(row["expected_revision"]),
        before_values=before,
        proposed_changes=changes,
        reason=cast(str, row["reason"]),
        evidence=tuple(evidence),
        model=cast(str, row["model"]),
        prompt_version=cast(str, row["prompt_version"]),
        status=cast(str, row["status"]),
        idempotency_key=cast(str, row["idempotency_key"]),
        created_at=cast(datetime | None, row["created_at"]),
    )
