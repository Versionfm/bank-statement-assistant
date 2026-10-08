from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from typing import Literal, Protocol, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from bank_statement_assistant.statements.models import ExtractedPage


class TransactionCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    booking_date: date
    description: str = Field(min_length=1, max_length=500)
    signed_amount: Decimal
    currency: str = Field(min_length=3, max_length=3)
    evidence_page_number: int = Field(ge=1)
    evidence_line_start: int | None = Field(default=None, ge=1)
    evidence_line_end: int | None = Field(default=None, ge=1)
    evidence_quote: str | None = Field(default=None, max_length=2000)
    booking_date_is_inherited: bool = False
    booking_date_evidence_page_number: int | None = Field(default=None, ge=1)
    booking_date_evidence_line_start: int | None = Field(default=None, ge=1)
    booking_date_evidence_line_end: int | None = Field(default=None, ge=1)
    booking_date_evidence_quote: str | None = Field(default=None, max_length=2000)
    confidence: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def evidence_span_is_complete(self) -> Self:
        if (self.evidence_line_start is None) != (self.evidence_line_end is None):
            raise ValueError("evidence line start and end must be supplied together")
        if (
            self.evidence_line_start is not None
            and self.evidence_line_end is not None
            and self.evidence_line_end < self.evidence_line_start
        ):
            raise ValueError("evidence line end must not precede its start")
        booking_evidence = (
            self.booking_date_evidence_page_number,
            self.booking_date_evidence_line_start,
            self.booking_date_evidence_line_end,
            self.booking_date_evidence_quote,
        )
        if self.booking_date_is_inherited and any(value is None for value in booking_evidence):
            raise ValueError("inherited booking dates require complete booking date evidence")
        if not self.booking_date_is_inherited and any(
            value is not None for value in booking_evidence
        ):
            raise ValueError("booking date evidence is only valid for inherited booking dates")
        if (
            self.booking_date_evidence_line_start is not None
            and self.booking_date_evidence_line_end is not None
            and self.booking_date_evidence_line_end < self.booking_date_evidence_line_start
        ):
            raise ValueError("booking date evidence line end must not precede its start")
        return self


ExtractionStrategy = Literal["deterministic"]


class ExtractionProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    detector_version: str = "unknown"
    detected_bank: str | None = None
    layout_id: str | None = None
    routing_evidence: tuple[str, ...] = ()
    parser_id: str = "unknown"
    parser_version: str = "unknown"
    extraction_strategy: ExtractionStrategy = "deterministic"
    automatic_acceptance_eligible: bool = False
    application_version: str = "unknown"
    model_name: str | None = None
    model_revision: str | None = None
    prompt_version: str | None = None
    schema_version: str | None = None


class StatementExtractor(Protocol):
    def extract(self, pages: Sequence[ExtractedPage]) -> "StatementExtraction": ...


class StatementExtraction(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    account_holder: str | None = Field(max_length=200)
    currency: str = Field(min_length=3, max_length=3)
    opening_balance: Decimal | None
    closing_balance: Decimal | None
    source_transaction_count: int | None = Field(ge=0)
    source_transaction_count_evidence_page_number: int | None = Field(ge=1)
    source_transaction_count_evidence_quote: str | None = Field(max_length=500)
    transactions: tuple[TransactionCandidate, ...] = Field(max_length=200)
    provenance: ExtractionProvenance = Field(default_factory=ExtractionProvenance)
