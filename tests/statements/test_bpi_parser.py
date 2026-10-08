import os
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from bank_statement_assistant.statements.bpi import BpiIntegratedStatementParser, BpiParseError
from bank_statement_assistant.statements.models import ExtractedPage
from bank_statement_assistant.statements.pdf import SafePdfReader
from bank_statement_assistant.statements.validation import validate_extraction


def test_parser_reconciles_a_synthetic_bpi_layout_across_a_page_break() -> None:
    pages = (
        ExtractedPage(
            number=1,
            text="\n".join(
                (
                    "EXTRACTO INTEGRADO",
                    "Período De 01/09/2025 a 30/09/2025",
                    "CONTA AGE Nº: 123 EUR",
                    "DEPÓSITOS À ORDEM",
                    "SALDO ANTERIOR CONTABILISTICO 10,00",
                    "01/09 01/09 Mercado -2,00 8,00",
                )
            ),
        ),
        ExtractedPage(
            number=2,
            text="\n".join(
                (
                    "           01/09 Café -1,00 7,00",
                    "SALDO ACTUAL CONTABILISTICO 7,00",
                )
            ),
        ),
    )

    extraction = BpiIntegratedStatementParser().extract(pages)
    validation = validate_extraction(extraction, pages=pages)

    inherited = extraction.transactions[1]
    assert inherited.booking_date == date(2025, 9, 1)
    assert inherited.booking_date_is_inherited
    assert inherited.booking_date_evidence_page_number == 1
    assert inherited.booking_date_evidence_quote == "01/09 01/09 Mercado -2,00 8,00"
    assert validation.is_valid


def test_parser_rejects_a_layout_missing_a_required_marker() -> None:
    pages = (
        ExtractedPage(
            number=1,
            text="\n".join(
                (
                    "EXTRACTO INTEGRADO",
                    "Período De 01/09/2025 a 30/09/2025",
                    "CONTA AGE Nº: 123 EUR",
                    "SALDO ANTERIOR CONTABILISTICO 10,00",
                    "01/09 01/09 Mercado -2,00 8,00",
                    "SALDO ACTUAL CONTABILISTICO 8,00",
                )
            ),
        ),
    )

    with pytest.raises(BpiParseError, match="required marker"):
        BpiIntegratedStatementParser().extract(pages)


def test_inherited_booking_date_evidence_must_match_its_claimed_line_span() -> None:
    pages = (
        ExtractedPage(
            number=1,
            text="\n".join(
                (
                    "EXTRACTO INTEGRADO",
                    "Período De 01/09/2025 a 30/09/2025",
                    "CONTA AGE Nº: 123 EUR",
                    "DEPÓSITOS À ORDEM",
                    "SALDO ANTERIOR CONTABILISTICO 10,00",
                    "01/09 01/09 Mercado -2,00 8,00",
                )
            ),
        ),
        ExtractedPage(
            number=2,
            text="\n".join(
                (
                    "           01/09 Café -1,00 7,00",
                    "SALDO ACTUAL CONTABILISTICO 7,00",
                )
            ),
        ),
    )
    extraction = BpiIntegratedStatementParser().extract(pages)
    inherited = extraction.transactions[1].model_copy(
        update={"booking_date_evidence_line_start": 1, "booking_date_evidence_line_end": 1}
    )
    tampered = extraction.model_copy(
        update={"transactions": (extraction.transactions[0], inherited)}
    )

    validation = validate_extraction(tampered, pages=pages)

    assert any(finding.code == "invalid_booking_date_evidence" for finding in validation.findings)


def test_parser_reconciles_the_configured_private_bpi_fixture() -> None:
    fixture = os.environ.get("BSA_PRIVATE_BPI_FIXTURE")
    if fixture is None:
        pytest.skip("set BSA_PRIVATE_BPI_FIXTURE to run the private BPI fixture")
    pages = SafePdfReader(max_bytes=1_000_000, max_pages=10).extract_text(
        content=Path(fixture).read_bytes()
    )

    extraction = BpiIntegratedStatementParser().extract(pages)
    validation = validate_extraction(extraction, pages=pages)

    assert extraction.provenance.extraction_strategy == "deterministic"
    assert extraction.currency == "EUR"
    assert extraction.opening_balance == Decimal("10.68")
    assert extraction.closing_balance == Decimal("910.42")
    assert len(extraction.transactions) == 59
    assert extraction.transactions[0].booking_date == date(2025, 9, 1)
    assert extraction.transactions[-1].booking_date == date(2025, 9, 29)
    assert any(transaction.booking_date_is_inherited for transaction in extraction.transactions)
    assert validation.is_valid
    assert validation.calculated_closing_balance == Decimal("910.42")
