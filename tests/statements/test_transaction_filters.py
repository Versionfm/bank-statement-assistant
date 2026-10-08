from decimal import Decimal

import pytest

from bank_statement_assistant.statements.transactions import TransactionFilters


@pytest.mark.parametrize(
    ("amount_min", "amount_max"),
    [(Decimal("101"), Decimal("100")), (Decimal("-1"), None), (None, Decimal("-1"))],
)
def test_transaction_filters_reject_invalid_amount_bounds(
    amount_min: Decimal | None, amount_max: Decimal | None
) -> None:
    with pytest.raises(ValueError):
        TransactionFilters(amount_min=amount_min, amount_max=amount_max)
