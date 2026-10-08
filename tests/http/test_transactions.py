from datetime import date
from decimal import Decimal
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient

from bank_statement_assistant.adapters.http.app import create_app
from bank_statement_assistant.statements.resolution import (
    ClassificationAcceptance,
    CorrectionCommand,
    CorrectionRecord,
    RevertCommand,
)
from bank_statement_assistant.statements.transactions import (
    Transaction,
    TransactionPage,
)

pytestmark = pytest.mark.anyio


class Ready:
    async def check(self) -> bool:
        return True


class FakeTransactions:
    def __init__(self, page: TransactionPage) -> None:
        self.page = page
        self.filters: object | None = None

    def list(self, *, filters: object) -> TransactionPage:
        self.filters = filters
        return self.page

    def get(self, transaction_id: UUID) -> Transaction | None:
        return next(
            (item for item in self.page.items if item.id == transaction_id),
            None,
        )

    def correct(self, transaction_id: UUID, command: CorrectionCommand) -> Transaction:
        assert transaction_id == self.page.items[0].id
        return self.page.items[0]

    def history(self, transaction_id: UUID) -> tuple[CorrectionRecord, ...]:
        assert transaction_id == self.page.items[0].id
        return ()

    def revert(self, transaction_id: UUID, command: RevertCommand) -> Transaction:
        assert transaction_id == self.page.items[0].id
        return self.page.items[0]

    def accept_classification(
        self, transaction_id: UUID, acceptance: ClassificationAcceptance
    ) -> Transaction:
        assert transaction_id == self.page.items[0].id
        return self.page.items[0]


async def test_list_transactions_returns_provisional_source_evidence() -> None:
    transaction = Transaction(
        id=UUID("50e5591f-913e-471b-a501-541fd860af30"),
        statement_id=UUID("da7abe2b-aac6-42e5-ae61-669e3ca11ebb"),
        statement_filename="statement.pdf",
        statement_status="needs_review",
        source_ordinal=1,
        booking_date=date(2025, 9, 1),
        description="Grocery Store",
        signed_amount=Decimal("-12.34"),
        currency="EUR",
        confidence=0.99,
        evidence_page_number=1,
        evidence_line_start=2,
        evidence_line_end=2,
        evidence_quote="01/09/2025 Grocery Store -12,34",
        review_findings=({"code": "balance_mismatch", "message": "Review required."},),
    )
    transactions = FakeTransactions(
        TransactionPage(items=(transaction,), total=1, limit=50, offset=0)
    )
    app = create_app(readiness=Ready(), transactions=transactions)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            "/api/transactions",
            params={"review_only": "true", "limit": "50"},
        )

    assert response.status_code == 200
    assert response.json() == {
        "items": [
            {
                "id": "50e5591f-913e-471b-a501-541fd860af30",
                "statement_id": "da7abe2b-aac6-42e5-ae61-669e3ca11ebb",
                "statement_filename": "statement.pdf",
                "statement_status": "needs_review",
                "source_ordinal": 1,
                "booking_date": "2025-09-01",
                "description": "Grocery Store",
                "signed_amount": "-12.34",
                "currency": "EUR",
                "confidence": 0.99,
                "reporting_category": None,
                "movement_kind": None,
                "payment_channel": None,
                "classification_status": "unclassified",
                "classification_confidence": None,
                "classification_provenance": None,
                "evidence_page_number": 1,
                "evidence_line_start": 2,
                "evidence_line_end": 2,
                "evidence_quote": "01/09/2025 Grocery Store -12,34",
                "review_findings": [{"code": "balance_mismatch", "message": "Review required."}],
            }
        ],
        "total": 1,
        "limit": 50,
        "offset": 0,
    }
    assert transactions.filters is not None


async def test_list_transactions_forwards_deterministic_filter_contract() -> None:
    transactions = FakeTransactions(TransactionPage(items=(), total=0, limit=50, offset=0))
    app = create_app(readiness=Ready(), transactions=transactions)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            "/api/transactions",
            params={
                "description": " mercado ",
                "amount_min": "100.00",
                "amount_max": "250.50",
                "movement_kind": "Transfer",
                "money_direction": "out",
                "classification_status": "classified",
                "payment_channel": "Bank Transfer",
                "transfer_scope": "external_party",
                "reporting_category": "Groceries",
                "currency": "EUR",
            },
        )

    assert response.status_code == 200
    filters = transactions.filters
    assert filters is not None
    assert filters.description_query == "mercado"
    assert filters.amount_min == Decimal("100.00")
    assert filters.amount_max == Decimal("250.50")
    assert filters.movement_kind == "Transfer"
    assert filters.money_direction == "out"
    assert filters.classification_status == "classified"
    assert filters.payment_channel == "Bank Transfer"
    assert filters.transfer_scope == "external_party"
    assert filters.reporting_category == "Groceries"
    assert filters.currency == "EUR"


async def test_list_transactions_rejects_invalid_amount_range() -> None:
    transactions = FakeTransactions(TransactionPage(items=(), total=0, limit=50, offset=0))
    app = create_app(readiness=Ready(), transactions=transactions)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            "/api/transactions",
            params={"amount_min": "250", "amount_max": "100"},
        )

    assert response.status_code == 422
    assert response.json()["detail"] == "amount_min must not be greater than amount_max"
    assert transactions.filters is None


async def test_transaction_resolution_endpoints_have_typed_contracts() -> None:
    transaction = Transaction(
        id=UUID("50e5591f-913e-471b-a501-541fd860af30"),
        statement_id=UUID("da7abe2b-aac6-42e5-ae61-669e3ca11ebb"),
        statement_filename="statement.pdf",
        statement_status="needs_review",
        source_ordinal=1,
        booking_date=date(2025, 9, 1),
        description="Grocery Store",
        signed_amount=Decimal("-12.34"),
        currency="EUR",
        confidence=0.99,
        evidence_page_number=1,
        evidence_line_start=2,
        evidence_line_end=2,
        evidence_quote="01/09/2025 Grocery Store -12,34",
        reporting_category="Groceries",
        movement_kind="Expense",
        payment_channel="Card",
        classification_status="needs_review",
        classification_id=7,
    )
    transactions = FakeTransactions(
        TransactionPage(items=(transaction,), total=1, limit=50, offset=0)
    )
    app = create_app(readiness=Ready(), transactions=transactions)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        correction = await client.post(
            f"/api/transactions/{transaction.id}/corrections",
            json={
                "expected_revision": 0,
                "description": "Supermarket",
                "reason": "Receipt confirms the merchant name",
                "idempotency_key": "correction-1",
            },
        )
        history = await client.get(f"/api/transactions/{transaction.id}/history")
        acceptance = await client.post(
            f"/api/transactions/{transaction.id}/classification/accept",
            json={"classification_id": 7, "idempotency_key": "accept-1"},
        )

    assert correction.status_code == 202
    assert history.status_code == 200
    assert history.json() == []
    assert acceptance.status_code == 202
