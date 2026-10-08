import re
from collections.abc import Sequence
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Literal

from bank_statement_assistant.statements.extraction import (
    ExtractionProvenance,
    StatementExtraction,
    TransactionCandidate,
)
from bank_statement_assistant.statements.models import ExtractedPage
from bank_statement_assistant.statements.parser_registry import BankLayoutId

BPI_INTEGRATED_LAYOUT = BankLayoutId("bpi.extracto-integrado.current-account.v1")
BPI_INTEGRATED_REQUIRED_MARKERS = (
    "EXTRACTO INTEGRADO",
    "DEPÓSITOS À ORDEM",
    "SALDO ANTERIOR CONTABILISTICO",
    "SALDO ACTUAL CONTABILISTICO",
)

_AMOUNT = r"[+-]?(?:\d{1,3}(?:\.\d{3})*|\d+),\d{2}"
_BOOKED_ROW = re.compile(
    rf"^(?P<booking>\d{{2}}/\d{{2}})\s+(?P<value>\d{{2}}/\d{{2}})\s+"
    rf"(?P<description>.+?)\s+(?P<amount>{_AMOUNT})\s+(?P<balance>{_AMOUNT})\s*$"
)
_INHERITED_ROW = re.compile(
    rf"^\s+(?P<value>\d{{2}}/\d{{2}})\s+(?P<description>.+?)\s+"
    rf"(?P<amount>{_AMOUNT})\s+(?P<balance>{_AMOUNT})\s*$"
)
_PERIOD = re.compile(r"Per[ií]odo\s+De\s+(\d{2}/\d{2}/\d{4})\s+a\s+(\d{2}/\d{2}/\d{4})")
_CURRENCY = re.compile(r"CONTA(?:\s+AGE)?\s+N[ºO]:.*?\b([A-Z]{3})\b")


class BpiParseError(ValueError):
    """The detected BPI layout does not satisfy the parser's fixed contract."""


class BpiIntegratedStatementParser:
    """Deterministically parse the verified BPI Extracto Integrado layout."""

    extraction_strategy: Literal["deterministic"] = "deterministic"
    parser_id = "bpi.extracto-integrado.current-account"
    parser_version = "1"

    def extract(self, pages: Sequence[ExtractedPage]) -> StatementExtraction:
        _require_layout_markers(pages)
        period_start, period_end = _statement_period(pages)
        currency = _statement_currency(pages)
        opening_balance = _labelled_balance(pages, "SALDO ANTERIOR CONTABILISTICO")
        closing_balance = _labelled_balance(pages, "SALDO ACTUAL CONTABILISTICO")
        transactions = _transactions(
            pages,
            period_start=period_start,
            period_end=period_end,
            currency=currency,
        )
        if not transactions:
            raise BpiParseError("BPI statement contains no movement rows")
        return StatementExtraction(
            account_holder=None,
            currency=currency,
            opening_balance=opening_balance,
            closing_balance=closing_balance,
            source_transaction_count=None,
            source_transaction_count_evidence_page_number=None,
            source_transaction_count_evidence_quote=None,
            transactions=tuple(transactions),
            provenance=ExtractionProvenance(
                parser_id=self.parser_id,
                parser_version=self.parser_version,
                extraction_strategy=self.extraction_strategy,
            ),
        )


def _statement_period(pages: Sequence[ExtractedPage]) -> tuple[date, date]:
    source = "\n".join(page.text for page in pages)
    match = _PERIOD.search(source)
    if match is None:
        raise BpiParseError("BPI statement period is missing or unreadable")
    start, end = (date.fromisoformat(_iso_date(value)) for value in match.groups())
    if end < start:
        raise BpiParseError("BPI statement period ends before it starts")
    return start, end


def _require_layout_markers(pages: Sequence[ExtractedPage]) -> None:
    source = "\n".join(page.text.casefold() for page in pages)
    missing = tuple(
        marker for marker in BPI_INTEGRATED_REQUIRED_MARKERS if marker.casefold() not in source
    )
    if missing:
        raise BpiParseError(f"BPI statement required marker is missing: {missing[0]}")


def _statement_currency(pages: Sequence[ExtractedPage]) -> str:
    source = "\n".join(page.text for page in pages)
    match = _CURRENCY.search(source)
    if match is None:
        raise BpiParseError("BPI statement currency is missing or unreadable")
    return match.group(1)


def _labelled_balance(pages: Sequence[ExtractedPage], label: str) -> Decimal:
    for page in pages:
        for line in page.text.splitlines():
            if label in line:
                amounts = re.findall(_AMOUNT, line)
                if amounts:
                    return _decimal(amounts[-1])
    raise BpiParseError(f"BPI statement {label.casefold()} is missing or unreadable")


def _transactions(
    pages: Sequence[ExtractedPage],
    *,
    period_start: date,
    period_end: date,
    currency: str,
) -> list[TransactionCandidate]:
    transactions: list[TransactionCandidate] = []
    in_current_account_section = False
    current_booking_date: date | None = None
    booking_evidence_page_number: int | None = None
    booking_evidence_line_number: int | None = None
    booking_evidence_quote: str | None = None
    group_line_start: int | None = None

    for page in pages:
        lines = page.text.splitlines()
        for line_number, line in enumerate(lines, start=1):
            if "SALDO ANTERIOR CONTABILISTICO" in line:
                in_current_account_section = True
                continue
            if "SALDO ACTUAL CONTABILISTICO" in line:
                return transactions
            if not in_current_account_section:
                continue

            booked = _BOOKED_ROW.match(line)
            inherited = _INHERITED_ROW.match(line) if booked is None else None
            match = booked or inherited
            if match is None:
                continue

            if booked is not None:
                current_booking_date = _date_in_period(
                    booked.group("booking"), period_start=period_start, period_end=period_end
                )
                group_line_start = line_number
                booking_evidence_page_number = page.number
                booking_evidence_line_number = line_number
                booking_evidence_quote = line
                inherited_booking_date = False
            else:
                if (
                    current_booking_date is None
                    or booking_evidence_page_number is None
                    or booking_evidence_line_number is None
                    or booking_evidence_quote is None
                ):
                    raise BpiParseError("BPI movement row has no preceding booking date")
                inherited_booking_date = True

            description = " ".join(match.group("description").split())
            if not description:
                raise BpiParseError("BPI movement row has an empty description")
            evidence_line_start = group_line_start if group_line_start is not None else line_number
            if inherited_booking_date and group_line_start is None:
                evidence_line_start = line_number
            transactions.append(
                TransactionCandidate(
                    booking_date=current_booking_date,
                    description=description,
                    signed_amount=_decimal(match.group("amount")),
                    currency=currency,
                    evidence_page_number=page.number,
                    evidence_line_start=evidence_line_start,
                    evidence_line_end=line_number,
                    evidence_quote="\n".join(lines[evidence_line_start - 1 : line_number]),
                    booking_date_is_inherited=inherited_booking_date,
                    booking_date_evidence_page_number=(
                        booking_evidence_page_number if inherited_booking_date else None
                    ),
                    booking_date_evidence_line_start=(
                        booking_evidence_line_number if inherited_booking_date else None
                    ),
                    booking_date_evidence_line_end=(
                        booking_evidence_line_number if inherited_booking_date else None
                    ),
                    booking_date_evidence_quote=(
                        booking_evidence_quote if inherited_booking_date else None
                    ),
                    confidence=1,
                )
            )
        group_line_start = None
    raise BpiParseError("BPI statement closing balance is missing")


def _date_in_period(day_month: str, *, period_start: date, period_end: date) -> date:
    day, month = (int(part) for part in day_month.split("/"))
    candidates: list[date] = []
    for year in range(period_start.year, period_end.year + 1):
        try:
            candidate = date(year, month, day)
        except ValueError:
            continue
        if period_start <= candidate <= period_end:
            candidates.append(candidate)
    if len(candidates) != 1:
        raise BpiParseError(f"BPI booking date {day_month} is outside the statement period")
    return candidates[0]


def _decimal(value: str) -> Decimal:
    try:
        return Decimal(value.replace(".", "").replace(",", "."))
    except InvalidOperation as error:
        raise BpiParseError(f"invalid BPI monetary amount: {value}") from error


def _iso_date(value: str) -> str:
    day, month, year = value.split("/")
    return f"{year}-{month}-{day}"
