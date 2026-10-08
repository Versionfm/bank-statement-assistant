from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal
from uuid import UUID

from bank_statement_assistant.statements.classification import TransferScope

ReportMovement = Literal["Expense", "Income", "Transfer", "Refund", "Fee"]
ReportGroup = Literal[
    "category",
    "counterparty",
    "payment_channel",
    "movement_kind",
    "transfer_direction",
    "transfer_scope",
]


@dataclass(frozen=True, slots=True)
class ReportQuery:
    month_from: str | None = None
    month_to: str | None = None
    statement_id: UUID | None = None
    currency: str = "EUR"
    reporting_category: str | None = None
    movement_kind: ReportMovement | None = None
    payment_channel: str | None = None
    counterparty: str | None = None
    include_provisional: bool = True


@dataclass(frozen=True, slots=True)
class ReportTransaction:
    id: UUID
    statement_id: UUID
    booking_date: date
    description: str
    signed_amount: Decimal
    currency: str
    reporting_category: str | None
    movement_kind: ReportMovement | None
    payment_channel: str | None
    counterparty: str | None
    transfer_scope: TransferScope | None = None
    is_provisional: bool = False
    is_unresolved: bool = False

    @property
    def month(self) -> str:
        return self.booking_date.strftime("%Y-%m")


@dataclass(frozen=True, slots=True)
class ReportTotals:
    income: Decimal = Decimal(0)
    gross_spending: Decimal = Decimal(0)
    refunds: Decimal = Decimal(0)
    net_spending: Decimal = Decimal(0)
    net_cash_flow: Decimal = Decimal(0)
    transfer_in: Decimal = Decimal(0)
    transfer_out: Decimal = Decimal(0)
    net_account_flow: Decimal = Decimal(0)


@dataclass(frozen=True, slots=True)
class BreakdownItem:
    label: str
    amount: Decimal
    transaction_count: int


@dataclass(frozen=True, slots=True)
class ReportQuality:
    is_provisional: bool
    provisional_count: int
    unresolved_count: int
    unresolved_amount: Decimal


@dataclass(frozen=True, slots=True)
class TransferSummary:
    count: int = 0
    total: Decimal = Decimal(0)
    incoming: Decimal = Decimal(0)
    outgoing: Decimal = Decimal(0)
    own_account_total: Decimal = Decimal(0)
    external_total: Decimal = Decimal(0)
    unknown_total: Decimal = Decimal(0)


@dataclass(frozen=True, slots=True)
class CurrencySummary:
    currency: str
    amount: Decimal
    transaction_count: int


@dataclass(frozen=True, slots=True)
class LargestTransaction:
    id: UUID
    booking_date: date
    description: str
    amount: Decimal
    currency: str
    counterparty: str | None
    reporting_category: str | None


@dataclass(frozen=True, slots=True)
class MonthlyReport:
    month: str
    totals: ReportTotals
    category_breakdown: tuple[BreakdownItem, ...]
    counterparty_breakdown: tuple[BreakdownItem, ...]
    payment_channel_breakdown: tuple[BreakdownItem, ...]
    largest_transactions: tuple[LargestTransaction, ...]
    transfers: TransferSummary
    quality: ReportQuality


@dataclass(frozen=True, slots=True)
class ReportOverview:
    totals: ReportTotals
    previous_period_change: Decimal | None


@dataclass(frozen=True, slots=True)
class ReportResult:
    overview: ReportOverview
    months: tuple[MonthlyReport, ...]
    non_eur: tuple[CurrencySummary, ...]
    non_eur_transactions: tuple[LargestTransaction, ...] = ()


@dataclass(frozen=True, slots=True)
class ReportDrilldownQuery:
    group: ReportGroup
    value: str
    offset: int = 0
    limit: int = 50


@dataclass(frozen=True, slots=True)
class ReportTransactionDetail:
    id: UUID
    booking_date: date
    description: str
    signed_amount: Decimal
    currency: str
    reporting_category: str | None
    movement_kind: ReportMovement | None
    payment_channel: str | None
    counterparty: str | None
    transfer_scope: TransferScope | None


@dataclass(frozen=True, slots=True)
class ReportTransactionPage:
    items: tuple[ReportTransactionDetail, ...]
    total: int
    limit: int
    offset: int
