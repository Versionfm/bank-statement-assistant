from datetime import date
from decimal import Decimal

import pytest

from bank_statement_assistant.statements.extraction import TransactionCandidate


def test_transaction_evidence_span_requires_both_inclusive_line_bounds() -> None:
    with pytest.raises(ValueError, match="supplied together"):
        TransactionCandidate(
            booking_date=date(2025, 9, 1),
            description="Grocery Store",
            signed_amount=Decimal("-12.34"),
            currency="EUR",
            evidence_page_number=1,
            evidence_line_start=2,
            confidence=1,
        )
