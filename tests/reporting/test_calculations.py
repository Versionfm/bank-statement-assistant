from datetime import date
from decimal import Decimal
from uuid import UUID

from bank_statement_assistant.reporting.calculations import calculate_report, drilldown_transactions
from bank_statement_assistant.reporting.models import (
    ReportDrilldownQuery,
    ReportQuery,
    ReportTransaction,
)


def transaction(
    ordinal: int,
    booking_date: date,
    amount: str,
    *,
    movement_kind: str,
    category: str | None = None,
    channel: str = "Card",
    counterparty: str | None = None,
    currency: str = "EUR",
    provisional: bool = False,
    transfer_scope: str | None = None,
) -> ReportTransaction:
    return ReportTransaction(
        id=UUID(int=ordinal),
        statement_id=UUID(int=100),
        booking_date=booking_date,
        description=f"Transaction {ordinal}",
        signed_amount=Decimal(amount),
        currency=currency,
        reporting_category=category,
        movement_kind=movement_kind,
        payment_channel=channel,
        counterparty=counterparty,
        is_provisional=provisional,
        transfer_scope=transfer_scope,
    )


def test_calculates_monthly_totals_and_breakdowns_from_effective_values() -> None:
    result = calculate_report(
        transactions=(
            transaction(1, date(2026, 8, 2), "250", movement_kind="Income", category="Salary"),
            transaction(
                2,
                date(2026, 8, 4),
                "-40",
                movement_kind="Expense",
                category="Groceries",
                counterparty="Market",
            ),
            transaction(
                3,
                date(2026, 8, 6),
                "-10",
                movement_kind="Fee",
                category="Bank Fees",
                channel="Bank Transfer",
            ),
            transaction(4, date(2026, 8, 8), "15", movement_kind="Refund", category="Groceries"),
            transaction(5, date(2026, 8, 9), "-100", movement_kind="Transfer"),
        ),
        query=ReportQuery(month_from="2026-08", month_to="2026-08"),
    )

    month = result.months[0]
    assert month.totals.income == Decimal("250")
    assert month.totals.gross_spending == Decimal("50")
    assert month.totals.refunds == Decimal("15")
    assert month.totals.net_spending == Decimal("35")
    assert month.totals.net_cash_flow == Decimal("215")
    assert month.transfers.total == Decimal("100")
    assert month.transfers.incoming == Decimal("0")
    assert month.transfers.outgoing == Decimal("100")
    assert month.totals.net_account_flow == Decimal("115")
    assert month.category_breakdown[0].label == "Groceries"
    assert month.category_breakdown[0].amount == Decimal("40")


def test_separates_non_eur_and_counts_provisional_rows() -> None:
    result = calculate_report(
        transactions=(
            transaction(
                1,
                date(2026, 9, 1),
                "-20",
                movement_kind="Expense",
                category="Shopping",
                currency="EUR",
                provisional=True,
            ),
            transaction(
                2,
                date(2026, 9, 2),
                "-30",
                movement_kind="Expense",
                category="Shopping",
                currency="USD",
            ),
        ),
        query=ReportQuery(month_from="2026-09", month_to="2026-09"),
    )

    month = result.months[0]
    assert month.totals.gross_spending == Decimal("20")
    assert month.quality.provisional_count == 1
    assert month.quality.unresolved_amount == Decimal("0")
    assert result.non_eur[0].currency == "USD"
    assert result.non_eur[0].amount == Decimal("30")
    assert result.non_eur_transactions[0].description == "Transaction 2"


def test_previous_period_change_requires_consecutive_months() -> None:
    result = calculate_report(
        transactions=(
            transaction(1, date(2026, 8, 1), "-20", movement_kind="Expense"),
            transaction(2, date(2026, 6, 1), "-10", movement_kind="Expense"),
        ),
        query=ReportQuery(),
    )

    assert result.overview.previous_period_change is None


def test_transfer_direction_and_scope_change_account_flow_only() -> None:
    result = calculate_report(
        transactions=(
            transaction(
                1,
                date(2026, 9, 1),
                "500",
                movement_kind="Transfer",
                transfer_scope="own_account",
            ),
            transaction(
                2,
                date(2026, 9, 2),
                "-70",
                movement_kind="Transfer",
                transfer_scope="external_party",
            ),
        ),
        query=ReportQuery(month_from="2026-09", month_to="2026-09"),
    )

    month = result.months[0]
    assert month.transfers.incoming == Decimal("500")
    assert month.transfers.outgoing == Decimal("70")
    assert month.transfers.own_account_total == Decimal("500")
    assert month.transfers.external_total == Decimal("70")
    assert month.transfers.unknown_total == Decimal("0")
    assert month.totals.net_cash_flow == Decimal("0")
    assert month.totals.net_account_flow == Decimal("430")


def test_drilldown_returns_exact_bucket_transactions_with_stable_pagination() -> None:
    rows = (
        transaction(1, date(2026, 9, 2), "-20", movement_kind="Expense", category="Groceries"),
        transaction(2, date(2026, 9, 3), "-30", movement_kind="Expense", category="Groceries"),
        transaction(3, date(2026, 9, 4), "-40", movement_kind="Expense", category="Shopping"),
    )
    page = drilldown_transactions(
        transactions=rows,
        query=ReportQuery(month_from="2026-09", month_to="2026-09"),
        drilldown=ReportDrilldownQuery(group="category", value="Groceries", limit=1),
    )

    assert page.total == 2
    assert page.items[0].id == UUID(int=2)
    assert page.items[0].reporting_category == "Groceries"


def test_unknown_transfer_scope_is_reconcilable() -> None:
    result = calculate_report(
        transactions=(
            transaction(1, date(2026, 9, 5), "25", movement_kind="Transfer"),
        ),
        query=ReportQuery(month_from="2026-09", month_to="2026-09"),
    )

    transfers = result.months[0].transfers
    assert transfers.total == Decimal("25")
    assert (
        transfers.own_account_total
        + transfers.external_total
        + transfers.unknown_total
        == transfers.total
    )
