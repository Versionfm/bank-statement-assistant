import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from bank_statement_assistant.statements.extraction import StatementExtraction, TransactionCandidate
from bank_statement_assistant.statements.models import ExtractedPage

VALIDATION_VERSION = "validation-v1"


@dataclass(frozen=True, slots=True)
class ValidationFinding:
    code: str
    message: str
    transaction_index: int | None = None


@dataclass(frozen=True, slots=True)
class ValidationResult:
    is_valid: bool
    calculated_closing_balance: Decimal | None
    difference: Decimal | None
    findings: tuple[ValidationFinding, ...]


def validate_effective_balances(
    *,
    opening_balance: Decimal | None,
    closing_balance: Decimal | None,
    signed_amounts: Sequence[Decimal],
) -> ValidationResult:
    """Validate corrected financial values without changing source evidence."""
    if opening_balance is None or closing_balance is None:
        return ValidationResult(
            is_valid=False,
            calculated_closing_balance=None,
            difference=None,
            findings=(
                ValidationFinding(
                    code="missing_balance",
                    message="Opening and closing balances are required for reconciliation.",
                ),
            ),
        )
    calculated = opening_balance + sum(signed_amounts, start=Decimal(0))
    difference = closing_balance - calculated
    findings = (
        ()
        if difference == 0
        else (
            ValidationFinding(
                code="balance_mismatch",
                message=(
                    "Opening balance plus effective transactions does not equal closing balance."
                ),
            ),
        )
    )
    return ValidationResult(
        is_valid=not findings,
        calculated_closing_balance=calculated,
        difference=difference,
        findings=findings,
    )


def validate_extraction(
    extraction: StatementExtraction,
    *,
    pages: Sequence[ExtractedPage],
) -> ValidationResult:
    findings: list[ValidationFinding] = []
    pages_by_number = {page.number: page for page in pages}
    seen_evidence: set[tuple[int, str]] = set()
    for index, transaction in enumerate(extraction.transactions):
        evidence_quote = transaction.evidence_quote
        evidence_key = (transaction.evidence_page_number, evidence_quote or "")
        if not _evidence_span_is_valid(transaction, pages_by_number):
            findings.append(
                ValidationFinding(
                    code="invalid_evidence_span",
                    message="Transaction evidence refers to lines outside its source page.",
                    transaction_index=index,
                )
            )
        elif not evidence_quote or not evidence_quote.strip():
            findings.append(
                ValidationFinding(
                    code="missing_evidence",
                    message="Transaction has no quoted source evidence.",
                    transaction_index=index,
                )
            )
        elif transaction.evidence_page_number not in pages_by_number:
            findings.append(
                ValidationFinding(
                    code="invalid_evidence_page",
                    message="Transaction evidence refers to a page outside the source PDF.",
                    transaction_index=index,
                )
            )
        elif evidence_quote not in pages_by_number[transaction.evidence_page_number].text:
            findings.append(
                ValidationFinding(
                    code="evidence_not_found",
                    message="Transaction evidence quote is not present on the claimed source page.",
                    transaction_index=index,
                )
            )
        elif transaction.booking_date_is_inherited and not _booking_date_evidence_is_valid(
            transaction, pages_by_number
        ):
            findings.append(
                ValidationFinding(
                    code="invalid_booking_date_evidence",
                    message=(
                        "Inherited booking date evidence is not present on its claimed source page."
                    ),
                    transaction_index=index,
                )
            )
        elif transaction.signed_amount not in _decimal_tokens(evidence_quote):
            findings.append(
                ValidationFinding(
                    code="amount_evidence_mismatch",
                    message="Transaction amount is not represented in its quoted source evidence.",
                    transaction_index=index,
                )
            )
        else:
            booking_date_quote = _booking_date_evidence(transaction) or evidence_quote
            if not _date_is_present(transaction.booking_date, booking_date_quote):
                findings.append(
                    ValidationFinding(
                        code="date_evidence_mismatch",
                        message=(
                            "Transaction booking date is not represented in its source evidence."
                        ),
                        transaction_index=index,
                    )
                )
            if _normalize_text(transaction.description) not in _normalize_text(evidence_quote):
                findings.append(
                    ValidationFinding(
                        code="description_evidence_mismatch",
                        message=(
                            "Transaction description is not represented in its source evidence."
                        ),
                        transaction_index=index,
                    )
                )
            if evidence_key in seen_evidence:
                findings.append(
                    ValidationFinding(
                        code="duplicate_transaction_evidence",
                        message="Multiple extracted transactions use the same source evidence.",
                        transaction_index=index,
                    )
                )
            seen_evidence.add(evidence_key)
        if transaction.currency.upper() != extraction.currency.upper():
            findings.append(
                ValidationFinding(
                    code="currency_mismatch",
                    message="Transaction currency differs from the statement currency.",
                    transaction_index=index,
                )
            )

    _validate_source_transaction_count(extraction, pages_by_number, findings)
    source_text = "\n".join(page.text for page in pages)
    if not _currency_is_present(extraction.currency, source_text):
        findings.append(
            ValidationFinding(
                code="currency_evidence_not_found",
                message="The statement currency is not present in the source text.",
            )
        )

    calculated: Decimal | None = None
    difference: Decimal | None = None
    if extraction.opening_balance is None or extraction.closing_balance is None:
        findings.append(
            ValidationFinding(
                code="missing_balance",
                message="Opening and closing balances are required for reconciliation.",
            )
        )
    else:
        normalized_source_text = _normalize_decimal_source(source_text)
        for label, balance in (
            ("opening", extraction.opening_balance),
            ("closing", extraction.closing_balance),
        ):
            if _compact_decimal(balance) not in normalized_source_text:
                findings.append(
                    ValidationFinding(
                        code=f"{label}_balance_evidence_not_found",
                        message=f"The {label} balance is not present in the source text.",
                    )
                )
        calculated = extraction.opening_balance + sum(
            (transaction.signed_amount for transaction in extraction.transactions),
            start=Decimal(0),
        )
        difference = extraction.closing_balance - calculated
        if difference != 0:
            findings.append(
                ValidationFinding(
                    code="balance_mismatch",
                    message="Opening balance plus transactions does not equal closing balance.",
                )
            )
    return ValidationResult(
        is_valid=not findings,
        calculated_closing_balance=calculated,
        difference=difference,
        findings=tuple(findings),
    )


def _booking_date_evidence(transaction: TransactionCandidate) -> str | None:
    if not transaction.booking_date_is_inherited:
        return None
    return transaction.booking_date_evidence_quote


def _booking_date_evidence_is_valid(
    transaction: TransactionCandidate,
    pages_by_number: dict[int, ExtractedPage],
) -> bool:
    page_number = transaction.booking_date_evidence_page_number
    quote = transaction.booking_date_evidence_quote
    line_start = transaction.booking_date_evidence_line_start
    line_end = transaction.booking_date_evidence_line_end
    if page_number is None or quote is None or line_start is None or line_end is None:
        return False
    page = pages_by_number.get(page_number)
    if page is None or line_end > len(page.text.splitlines(keepends=True)):
        return False
    source_span = "".join(page.text.splitlines(keepends=True)[line_start - 1 : line_end])
    return quote == source_span.rstrip("\r\n")


def _compact_decimal(value: Decimal) -> str:
    rendered = format(value, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered


def _normalize_text(value: str) -> str:
    return " ".join(value.casefold().split())


def _date_is_present(value: date, source: str) -> bool:
    return any(
        rendered in source
        for rendered in (
            value.isoformat(),
            value.strftime("%d/%m/%Y"),
            value.strftime("%d-%m-%Y"),
            value.strftime("%d.%m.%Y"),
            value.strftime("%d/%m/%y"),
            value.strftime("%d/%m"),
        )
    )


def _currency_is_present(currency: str, source: str) -> bool:
    return (
        re.search(
            rf"(?<![A-Z]){re.escape(currency.upper())}(?![A-Z])",
            source.upper(),
        )
        is not None
    ) or (currency.upper() == "EUR" and "€" in source)


def _evidence_span_is_valid(
    transaction: TransactionCandidate,
    pages_by_number: dict[int, ExtractedPage],
) -> bool:
    line_start = transaction.evidence_line_start
    line_end = transaction.evidence_line_end
    if line_start is None and line_end is None:
        return True
    page = pages_by_number.get(transaction.evidence_page_number)
    if page is None or line_start is None or line_end is None:
        return False
    line_count = len(page.text.splitlines(keepends=True))
    return line_start <= line_end <= line_count


def _decimal_tokens(value: str) -> set[Decimal]:
    tokens: set[Decimal] = set()
    for match in re.finditer(
        r"(?<![\w.])[+-]?(?:\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d+(?:[.,]\d+)?)(?![\w.])",
        value,
    ):
        try:
            rendered = match.group()
            if "." in rendered and "," in rendered:
                rendered = rendered.replace(".", "").replace(",", ".")
            else:
                rendered = rendered.replace(",", ".")
            tokens.add(Decimal(rendered))
        except ArithmeticError:
            continue
    return tokens


def _normalize_decimal_source(source: str) -> str:
    grouped_number = re.compile(r"(?<![\w.])[+-]?\d{1,3}(?:\.\d{3})+(?:,\d+)?(?![\w.])")

    def ungroup(match: re.Match[str]) -> str:
        rendered = match.group()
        if "," in rendered:
            return rendered.replace(".", "").replace(",", ".")
        return rendered.replace(".", "")

    return grouped_number.sub(ungroup, source).replace(",", ".")


def _validate_source_transaction_count(
    extraction: StatementExtraction,
    pages_by_number: dict[int, ExtractedPage],
    findings: list[ValidationFinding],
) -> None:
    count = extraction.source_transaction_count
    page_number = extraction.source_transaction_count_evidence_page_number
    quote = extraction.source_transaction_count_evidence_quote
    if count is None:
        return
    if page_number is None or quote is None or not quote.strip():
        findings.append(
            ValidationFinding(
                code="missing_source_row_count",
                message="The statement has no explicit, quoted transaction row count.",
            )
        )
        return
    page = pages_by_number.get(page_number)
    if page is None or quote not in page.text:
        findings.append(
            ValidationFinding(
                code="source_row_count_evidence_not_found",
                message="The quoted transaction row count is not present on its source page.",
            )
        )
        return
    if "transaction" not in quote.casefold() or Decimal(count) not in _decimal_tokens(quote):
        findings.append(
            ValidationFinding(
                code="source_row_count_evidence_mismatch",
                message="The source row-count quote does not represent the extracted count.",
            )
        )
    if count != len(extraction.transactions):
        findings.append(
            ValidationFinding(
                code="transaction_row_count_mismatch",
                message="Extracted transaction count differs from the statement's declared count.",
            )
        )
