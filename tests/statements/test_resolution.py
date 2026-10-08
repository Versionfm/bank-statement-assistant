from datetime import date
from decimal import Decimal

import pytest

from bank_statement_assistant.statements.resolution import (
    ResolutionError,
    TransactionValues,
    apply_changes,
    correction_from_values,
)


def values() -> TransactionValues:
    return TransactionValues(
        booking_date=date(2026, 8, 2),
        description="Market",
        signed_amount=Decimal("-20.00"),
        currency="EUR",
        reporting_category="Groceries",
        movement_kind="Expense",
        payment_channel="Card",
    )


def test_apply_changes_returns_a_valid_effective_snapshot() -> None:
    result = apply_changes(values(), {"description": " Supermarket "})

    assert result.description == "Supermarket"
    assert result.signed_amount == Decimal("-20.00")


def test_transfer_correction_cannot_retain_a_reporting_category() -> None:
    with pytest.raises(ResolutionError, match="transfers must not"):
        apply_changes(values(), {"movement_kind": "Transfer"})


def test_correction_has_a_monotonic_revision_and_reason() -> None:
    correction = correction_from_values(
        current_revision=2,
        current=values(),
        changes={"reporting_category": "Housing"},
        reason="Confirmed against the receipt",
    )

    assert correction.revision == 3
    assert correction.previous_revision == 2
    assert correction.values.reporting_category == "Housing"
    assert correction.classification_changed is True


def test_source_value_correction_does_not_resolve_classification_review() -> None:
    correction = correction_from_values(
        current_revision=0,
        current=values(),
        changes={"description": "Supermarket"},
        reason="Receipt confirms the merchant name",
    )

    assert correction.classification_changed is False


def test_unchanged_classification_value_does_not_resolve_classification_review() -> None:
    current = values()
    correction = correction_from_values(
        current_revision=1,
        current=current,
        changes={"reporting_category": current.reporting_category},
        reason="Confirm existing category",
    )

    assert correction.classification_changed is False


def test_clearing_classification_does_not_resolve_classification_review() -> None:
    correction = correction_from_values(
        current_revision=1,
        current=values(),
        changes={"movement_kind": None, "reporting_category": None, "payment_channel": None},
        reason="Classification is uncertain",
    )

    assert correction.classification_changed is False


def test_transfer_scope_is_valid_only_for_transfers() -> None:
    corrected = apply_changes(
        values(),
        {
            "movement_kind": "Transfer",
            "reporting_category": None,
            "transfer_scope": "external_party",
        },
    )
    assert corrected.transfer_scope == "external_party"

    with pytest.raises(ResolutionError, match="transfer scope"):
        apply_changes(values(), {"transfer_scope": "external_party"})


def test_transfer_scope_correction_resolves_transfer_classification() -> None:
    current = apply_changes(
        values(),
        {
            "movement_kind": "Transfer",
            "reporting_category": None,
            "payment_channel": "Bank Transfer",
        },
    )
    correction = correction_from_values(
        current_revision=0,
        current=current,
        changes={"transfer_scope": "own_account"},
        reason="Confirmed this is between my accounts",
    )

    assert correction.classification_changed is True


def test_correction_rejects_empty_changes_and_reason() -> None:
    with pytest.raises(ResolutionError, match="at least one"):
        correction_from_values(
            current_revision=0,
            current=values(),
            changes={},
            reason="reason",
        )
    with pytest.raises(ResolutionError, match="reason"):
        correction_from_values(
            current_revision=0,
            current=values(),
            changes={"description": "Other"},
            reason=" ",
        )
