from decimal import Decimal

from bank_statement_assistant.statements.extraction import (
    StatementExtraction,
    TransactionCandidate,
)
from bank_statement_assistant.statements.models import ExtractedPage
from bank_statement_assistant.statements.validation import validate_extraction


def extraction(
    *,
    closing: str = "80.00",
    amount: str = "-20.00",
    quote: str = "2026-08-02 Groceries -20.00 EUR",
    source_count: int | None = 1,
) -> StatementExtraction:
    return StatementExtraction.model_validate(
        {
            "account_holder": "Ana Example",
            "currency": "EUR",
            "opening_balance": "100.00",
            "closing_balance": closing,
            "source_transaction_count": source_count,
            "source_transaction_count_evidence_page_number": 1,
            "source_transaction_count_evidence_quote": "Transaction Count: 1",
            "transactions": [
                TransactionCandidate(
                    booking_date="2026-08-02",
                    description="Groceries",
                    signed_amount=Decimal(amount),
                    currency="EUR",
                    evidence_page_number=1,
                    evidence_quote=quote,
                    confidence=0.99,
                )
            ],
        }
    )


def test_validation_reconciles_with_exact_decimal_arithmetic() -> None:
    result = validate_extraction(
        extraction(),
        pages=(
            ExtractedPage(
                number=1,
                text=(
                    "Opening 100.00\nTransaction Count: 1\n"
                    "2026-08-02 Groceries -20.00 EUR\nClosing 80.00"
                ),
            ),
        ),
    )

    assert result.is_valid is True
    assert result.calculated_closing_balance == Decimal("80.00")
    assert result.difference == Decimal("0.00")
    assert result.findings == ()


def test_validation_routes_unreconciled_or_ungrounded_output_to_review() -> None:
    result = validate_extraction(
        extraction(closing="79.99", quote=""),
        pages=(
            ExtractedPage(number=1, text="Opening 100.00\nTransaction Count: 1\nClosing 79.99"),
        ),
    )

    assert result.is_valid is False
    assert result.difference == Decimal("-0.01")
    assert {finding.code for finding in result.findings} == {
        "balance_mismatch",
        "missing_evidence",
        "currency_evidence_not_found",
    }


def test_validation_rejects_fabricated_or_mismatched_source_evidence() -> None:
    result = validate_extraction(
        extraction(quote="invented evidence"),
        pages=(
            ExtractedPage(
                number=1,
                text=(
                    "Opening 100.00\nTransaction Count: 1\n"
                    "2026-08-02 Groceries -20.00 EUR\nClosing 80.00"
                ),
            ),
        ),
    )

    assert result.is_valid is False
    assert {finding.code for finding in result.findings} == {"evidence_not_found"}

    mismatched_amount = validate_extraction(
        extraction(closing="81.00", amount="-19.00"),
        pages=(
            ExtractedPage(
                number=1,
                text=(
                    "Opening 100.00\nTransaction Count: 1\n"
                    "2026-08-02 Groceries -20.00 EUR\nClosing 81.00"
                ),
            ),
        ),
    )
    assert {finding.code for finding in mismatched_amount.findings} == {"amount_evidence_mismatch"}


def test_validation_rejects_sign_field_and_row_count_mismatches() -> None:
    pages = (
        ExtractedPage(
            number=1,
            text=(
                "Opening 100.00\nTransaction Count: 1\n"
                "2026-08-02 Groceries -20.00 EUR\nClosing 120.00"
            ),
        ),
    )
    sign_mismatch = validate_extraction(
        extraction(closing="120.00", amount="20.00"),
        pages=pages,
    )
    assert "amount_evidence_mismatch" in {finding.code for finding in sign_mismatch.findings}

    field_mismatch = validate_extraction(
        extraction(quote="2026-08-03 Fuel -20.00 USD"),
        pages=(
            ExtractedPage(
                number=1,
                text=(
                    "Opening 100.00\nTransaction Count: 1\n"
                    "2026-08-03 Fuel -20.00 USD\nClosing 80.00"
                ),
            ),
        ),
    )
    assert {
        "date_evidence_mismatch",
        "description_evidence_mismatch",
        "currency_evidence_not_found",
    }.issubset({finding.code for finding in field_mismatch.findings})

    no_count = validate_extraction(extraction(source_count=None), pages=pages)
    assert "missing_source_row_count" not in {finding.code for finding in no_count.findings}


def test_validation_accepts_localized_row_evidence_and_statement_currency() -> None:
    result = validate_extraction(
        StatementExtraction(
            account_holder="Ana Example",
            currency="EUR",
            opening_balance=Decimal("100.00"),
            closing_balance=Decimal("87.66"),
            source_transaction_count=None,
            source_transaction_count_evidence_page_number=None,
            source_transaction_count_evidence_quote=None,
            transactions=(
                TransactionCandidate(
                    booking_date="2025-09-01",
                    description="Grocery Store",
                    signed_amount=Decimal("-12.34"),
                    currency="EUR",
                    evidence_page_number=1,
                    evidence_quote="01/09/2025 Grocery Store -12,34",
                    confidence=0.99,
                ),
            ),
        ),
        pages=(
            ExtractedPage(
                number=1,
                text=(
                    "Currency: EUR\nOpening 100,00\n01/09/2025 Grocery Store -12,34\nClosing 87,66"
                ),
            ),
        ),
    )

    assert result.is_valid is True
    assert result.findings == ()


def test_validation_reports_an_invalid_evidence_line_span() -> None:
    result = validate_extraction(
        StatementExtraction(
            account_holder=None,
            currency="EUR",
            opening_balance=None,
            closing_balance=None,
            source_transaction_count=None,
            source_transaction_count_evidence_page_number=None,
            source_transaction_count_evidence_quote=None,
            transactions=(
                TransactionCandidate(
                    booking_date="2025-09-01",
                    description="Grocery Store",
                    signed_amount=Decimal("-12.34"),
                    currency="EUR",
                    evidence_page_number=1,
                    evidence_line_start=4,
                    evidence_line_end=4,
                    confidence=0.99,
                ),
            ),
        ),
        pages=(ExtractedPage(number=1, text="01/09/2025 Grocery Store -12,34 EUR"),),
    )

    assert result.is_valid is False
    assert "invalid_evidence_span" in {finding.code for finding in result.findings}


def test_validation_accepts_portuguese_thousands_separators() -> None:
    result = validate_extraction(
        StatementExtraction(
            account_holder=None,
            currency="EUR",
            opening_balance=Decimal("1234.56"),
            closing_balance=Decimal("1222.22"),
            source_transaction_count=None,
            source_transaction_count_evidence_page_number=None,
            source_transaction_count_evidence_quote=None,
            transactions=(
                TransactionCandidate(
                    booking_date="2025-09-01",
                    description="Grocery Store",
                    signed_amount=Decimal("-12.34"),
                    currency="EUR",
                    evidence_page_number=1,
                    evidence_quote="01/09/2025 Grocery Store -12,34 EUR",
                    confidence=0.99,
                ),
            ),
        ),
        pages=(
            ExtractedPage(
                number=1,
                text=(
                    "Currency: EUR\nOpening 1.234,56\n"
                    "01/09/2025 Grocery Store -12,34 EUR\nClosing 1.222,22"
                ),
            ),
        ),
    )

    assert result.is_valid is True
    assert result.findings == ()
