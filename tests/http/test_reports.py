from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient

from bank_statement_assistant.adapters.http.app import create_app
from bank_statement_assistant.reporting.models import (
    ReportDrilldownQuery,
    ReportOverview,
    ReportQuery,
    ReportResult,
    ReportTotals,
    ReportTransactionPage,
)

pytestmark = pytest.mark.anyio


class Ready:
    async def check(self) -> bool:
        return True


class FakeReporting:
    def report(self, query: ReportQuery) -> ReportResult:
        assert query.currency == "EUR"
        assert query.month_from == "2026-08"
        return ReportResult(
            overview=ReportOverview(
                totals=ReportTotals(income=Decimal("100"), net_cash_flow=Decimal("80")),
                previous_period_change=Decimal("-5"),
            ),
            months=(),
            non_eur=(),
        )

    def drilldown(
        self, query: ReportQuery, drilldown: ReportDrilldownQuery
    ) -> ReportTransactionPage:
        assert drilldown.group == "transfer_direction"
        return ReportTransactionPage(
            items=(), total=0, limit=drilldown.limit, offset=drilldown.offset
        )


async def test_report_endpoint_returns_exact_decimal_strings() -> None:
    app = create_app(readiness=Ready(), reporting=FakeReporting())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/reports", params={"month_from": "2026-08"})

    assert response.status_code == 200
    assert response.json()["overview"] == {
        "totals": {
            "income": "100",
            "gross_spending": "0",
            "refunds": "0",
            "net_spending": "0",
            "net_cash_flow": "80",
            "transfer_in": "0",
            "transfer_out": "0",
            "net_account_flow": "0",
        },
        "previous_period_change": "-5",
    }


async def test_report_rejects_reversed_month_range() -> None:
    app = create_app(readiness=Ready(), reporting=FakeReporting())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            "/api/reports", params={"month_from": "2026-09", "month_to": "2026-08"}
        )

    assert response.status_code == 422


async def test_report_drilldown_returns_a_paginated_page() -> None:
    app = create_app(readiness=Ready(), reporting=FakeReporting())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            "/api/reports/transactions",
            params={"group": "transfer_direction", "value": "out", "limit": "10"},
        )

    assert response.status_code == 200
    assert response.json() == {"items": [], "total": 0, "limit": 10, "offset": 0}
