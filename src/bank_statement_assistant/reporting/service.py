from typing import Protocol

from bank_statement_assistant.reporting.calculations import calculate_report, drilldown_transactions
from bank_statement_assistant.reporting.models import (
    ReportDrilldownQuery,
    ReportQuery,
    ReportResult,
    ReportTransaction,
    ReportTransactionPage,
)


class ReportTransactionSource(Protocol):
    def list_report_transactions(self) -> tuple[ReportTransaction, ...]: ...


class ReportingService:
    """Application service for live, deterministic reports over effective values."""

    def __init__(self, source: ReportTransactionSource) -> None:
        self._source = source

    def report(self, query: ReportQuery) -> ReportResult:
        return calculate_report(transactions=self._source.list_report_transactions(), query=query)

    def drilldown(
        self, query: ReportQuery, drilldown: ReportDrilldownQuery
    ) -> ReportTransactionPage:
        return drilldown_transactions(
            transactions=self._source.list_report_transactions(),
            query=query,
            drilldown=drilldown,
        )
