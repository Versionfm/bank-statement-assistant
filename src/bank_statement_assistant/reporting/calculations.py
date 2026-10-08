from collections import defaultdict
from collections.abc import Callable, Iterable
from datetime import date
from decimal import Decimal

from bank_statement_assistant.reporting.models import (
    BreakdownItem,
    CurrencySummary,
    LargestTransaction,
    MonthlyReport,
    ReportDrilldownQuery,
    ReportOverview,
    ReportQuality,
    ReportQuery,
    ReportResult,
    ReportTotals,
    ReportTransaction,
    ReportTransactionDetail,
    ReportTransactionPage,
    TransferSummary,
)

ZERO = Decimal(0)


def drilldown_transactions(
    *,
    transactions: Iterable[ReportTransaction],
    query: ReportQuery,
    drilldown: ReportDrilldownQuery,
) -> ReportTransactionPage:
    if drilldown.offset < 0 or drilldown.limit < 1 or drilldown.limit > 100:
        raise ValueError("drilldown pagination is invalid")
    rows = tuple(
        row
        for transaction in transactions
        if (row := _included(transaction, query)) is not None
        and row.currency.upper() == query.currency.upper()
        and _drilldown_scope(row, drilldown.group)
        and _group_value(row, drilldown.group) == drilldown.value
    )
    rows = tuple(sorted(rows, key=lambda row: (row.booking_date, row.id), reverse=True))
    page = rows[drilldown.offset : drilldown.offset + drilldown.limit]
    return ReportTransactionPage(
        items=tuple(
            ReportTransactionDetail(
                id=row.id,
                booking_date=row.booking_date,
                description=row.description,
                signed_amount=row.signed_amount,
                currency=row.currency,
                reporting_category=row.reporting_category,
                movement_kind=row.movement_kind,
                payment_channel=row.payment_channel,
                counterparty=row.counterparty,
                transfer_scope=row.transfer_scope,
            )
            for row in page
        ),
        total=len(rows),
        limit=drilldown.limit,
        offset=drilldown.offset,
    )


def calculate_report(
    *, transactions: Iterable[ReportTransaction], query: ReportQuery
) -> ReportResult:
    rows = tuple(
        included
        for transaction in transactions
        if (included := _included(transaction, query)) is not None
    )
    by_month: dict[str, list[ReportTransaction]] = defaultdict(list)
    non_eur: dict[str, list[ReportTransaction]] = defaultdict(list)
    for transaction in rows:
        if transaction.currency.upper() == query.currency.upper():
            by_month[transaction.month].append(transaction)
        else:
            non_eur[transaction.currency.upper()].append(transaction)

    months = tuple(
        _monthly_report(month, tuple(by_month[month]), query.currency.upper())
        for month in sorted(by_month, reverse=True)
    )
    totals = _sum_totals(rows, query.currency.upper())
    previous_period_change = _previous_period_change(months)
    return ReportResult(
        overview=ReportOverview(totals=totals, previous_period_change=previous_period_change),
        months=months,
        non_eur=tuple(
            CurrencySummary(
                currency=currency,
                amount=sum((_absolute_amount(row) for row in values), ZERO),
                transaction_count=len(values),
            )
            for currency, values in sorted(non_eur.items())
        ),
        non_eur_transactions=tuple(
            LargestTransaction(
                id=row.id,
                booking_date=row.booking_date,
                description=row.description,
                amount=_absolute_amount(row),
                currency=row.currency,
                counterparty=row.counterparty,
                reporting_category=row.reporting_category,
            )
            for row in sorted(rows, key=_absolute_amount, reverse=True)
            if row.currency.upper() != query.currency.upper()
        ),
    )


def _included(
    transaction: ReportTransaction, query: ReportQuery
) -> ReportTransaction | None:
    if query.statement_id is not None and transaction.statement_id != query.statement_id:
        return None
    if not query.include_provisional and transaction.is_provisional:
        return None
    if query.month_from and transaction.month < query.month_from:
        return None
    if query.month_to and transaction.month > query.month_to:
        return None
    if query.reporting_category and transaction.reporting_category != query.reporting_category:
        return None
    if query.movement_kind and transaction.movement_kind != query.movement_kind:
        return None
    if query.payment_channel and transaction.payment_channel != query.payment_channel:
        return None
    if query.counterparty and transaction.counterparty != query.counterparty:
        return None
    return transaction


def _monthly_report(
    month: str, rows: tuple[ReportTransaction, ...], currency: str
) -> MonthlyReport:
    currency_rows = tuple(row for row in rows if row.currency.upper() == currency)
    spending = tuple(row for row in currency_rows if row.movement_kind in {"Expense", "Fee"})
    totals = _sum_totals(currency_rows, currency)
    unresolved = tuple(row for row in currency_rows if row.is_unresolved)
    return MonthlyReport(
        month=month,
        totals=totals,
        category_breakdown=_breakdown(
            spending, lambda row: row.reporting_category or "Unclassified"
        ),
        counterparty_breakdown=_breakdown(spending, lambda row: row.counterparty or "Unknown"),
        payment_channel_breakdown=_breakdown(
            spending, lambda row: row.payment_channel or "Unknown"
        ),
        largest_transactions=tuple(
            LargestTransaction(
                id=row.id,
                booking_date=row.booking_date,
                description=row.description,
                amount=_absolute_amount(row),
                currency=row.currency,
                counterparty=row.counterparty,
                reporting_category=row.reporting_category,
            )
            for row in sorted(spending, key=_absolute_amount, reverse=True)[:10]
        ),
        transfers=TransferSummary(
            count=sum(row.movement_kind == "Transfer" for row in currency_rows),
            total=sum(
                (_absolute_amount(row) for row in currency_rows if row.movement_kind == "Transfer"),
                ZERO,
            ),
            incoming=sum(
                (
                    row.signed_amount
                    for row in currency_rows
                    if row.movement_kind == "Transfer" and row.signed_amount > ZERO
                ),
                ZERO,
            ),
            outgoing=sum(
                (
                    _absolute_amount(row)
                    for row in currency_rows
                    if row.movement_kind == "Transfer" and row.signed_amount < ZERO
                ),
                ZERO,
            ),
            own_account_total=sum(
                (
                    _absolute_amount(row)
                    for row in currency_rows
                    if row.movement_kind == "Transfer" and row.transfer_scope == "own_account"
                ),
                ZERO,
            ),
            external_total=sum(
                (
                    _absolute_amount(row)
                    for row in currency_rows
                    if row.movement_kind == "Transfer"
                    and row.transfer_scope == "external_party"
                ),
                ZERO,
            ),
            unknown_total=sum(
                (
                    _absolute_amount(row)
                    for row in currency_rows
                    if row.movement_kind == "Transfer"
                    and row.transfer_scope not in {"own_account", "external_party"}
                ),
                ZERO,
            ),
        ),
        quality=ReportQuality(
            is_provisional=any(row.is_provisional for row in rows),
            provisional_count=sum(row.is_provisional for row in rows),
            unresolved_count=len(unresolved),
            unresolved_amount=sum((_absolute_amount(row) for row in unresolved), ZERO),
        ),
    )


def _sum_totals(rows: Iterable[ReportTransaction], currency: str) -> ReportTotals:
    eur_rows = tuple(row for row in rows if row.currency.upper() == currency)
    income = sum((_absolute_amount(row) for row in eur_rows if row.movement_kind == "Income"), ZERO)
    spending = sum(
        (_absolute_amount(row) for row in eur_rows if row.movement_kind in {"Expense", "Fee"}),
        ZERO,
    )
    refunds = sum(
        (_absolute_amount(row) for row in eur_rows if row.movement_kind == "Refund"), ZERO
    )
    transfer_in = sum(
        (
            row.signed_amount
            for row in eur_rows
            if row.movement_kind == "Transfer" and row.signed_amount > ZERO
        ),
        ZERO,
    )
    transfer_out = sum(
        (
            _absolute_amount(row)
            for row in eur_rows
            if row.movement_kind == "Transfer" and row.signed_amount < ZERO
        ),
        ZERO,
    )
    return ReportTotals(
        income=income,
        gross_spending=spending,
        refunds=refunds,
        net_spending=spending - refunds,
        net_cash_flow=income + refunds - spending,
        transfer_in=transfer_in,
        transfer_out=transfer_out,
        net_account_flow=income + refunds - spending + transfer_in - transfer_out,
    )


def _breakdown(
    rows: Iterable[ReportTransaction], label: Callable[[ReportTransaction], str]
) -> tuple[BreakdownItem, ...]:
    grouped: dict[str, list[ReportTransaction]] = defaultdict(list)
    for row in rows:
        grouped[label(row)].append(row)
    return tuple(
        BreakdownItem(
            label=name,
            amount=sum((_absolute_amount(row) for row in values), ZERO),
            transaction_count=len(values),
        )
        for name, values in sorted(
            grouped.items(),
            key=lambda item: sum((_absolute_amount(row) for row in item[1]), ZERO),
            reverse=True,
        )
    )


def _absolute_amount(row: ReportTransaction) -> Decimal:
    return abs(row.signed_amount)


def _group_value(row: ReportTransaction, group: str) -> str:
    if group == "category":
        return row.reporting_category or "Unclassified"
    if group == "counterparty":
        return row.counterparty or "Unknown"
    if group == "payment_channel":
        return row.payment_channel or "Unknown"
    if group == "movement_kind":
        return row.movement_kind or "Unclassified"
    if group == "transfer_direction":
        if row.movement_kind != "Transfer":
            return ""
        return "in" if row.signed_amount > ZERO else "out"
    if group == "transfer_scope":
        if row.movement_kind != "Transfer":
            return ""
        return row.transfer_scope or "unknown"
    raise ValueError(f"unsupported report group: {group}")


def _drilldown_scope(row: ReportTransaction, group: str) -> bool:
    if group in {"category", "counterparty", "payment_channel"}:
        return row.movement_kind in {"Expense", "Fee"}
    return True


def _previous_period_change(months: tuple[MonthlyReport, ...]) -> Decimal | None:
    if len(months) < 2:
        return None
    newest = date.fromisoformat(f"{months[0].month}-01")
    previous_year, previous_month = (
        (newest.year - 1, 12) if newest.month == 1 else (newest.year, newest.month - 1)
    )
    if months[1].month != f"{previous_year:04d}-{previous_month:02d}":
        return None
    return months[0].totals.net_spending - months[1].totals.net_spending
