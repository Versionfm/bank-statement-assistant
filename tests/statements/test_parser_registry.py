from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, cast

import pytest

from bank_statement_assistant.statements.extraction import (
    ExtractionProvenance,
    StatementExtraction,
)
from bank_statement_assistant.statements.models import ExtractedPage
from bank_statement_assistant.statements.parser_registry import (
    BankLayoutId,
    BankLayoutMatch,
    BankLayoutRule,
    KeywordBankDetector,
    ParserRegistry,
    RegisteredParser,
    StatementExtractionRouter,
    UnsupportedStatementLayoutError,
)


def extraction() -> StatementExtraction:
    return StatementExtraction.model_validate(
        {
            "account_holder": None,
            "currency": "EUR",
            "opening_balance": None,
            "closing_balance": None,
            "source_transaction_count": None,
            "source_transaction_count_evidence_page_number": None,
            "source_transaction_count_evidence_quote": None,
            "transactions": [],
            "provenance": {
                "detector_version": "legacy",
                "parser_id": "test.parser",
                "parser_version": "1",
            },
        }
    )


class FakeParser:
    parser_id = "test.parser"
    parser_version = "test-parser-v1"
    extraction_strategy: Literal["deterministic"] = "deterministic"

    def __init__(self) -> None:
        self.calls = 0

    def extract(self, pages: Sequence[ExtractedPage]) -> StatementExtraction:
        assert pages
        self.calls += 1
        return extraction()


@dataclass(frozen=True)
class FakeDetector:
    match: BankLayoutMatch | None

    @property
    def version(self) -> str:
        return "test-detector-v1"

    def detect(self, pages: Sequence[ExtractedPage]) -> BankLayoutMatch | None:
        assert pages
        return self.match


def test_registry_routes_verified_layout_to_deterministic_parser() -> None:
    layout_id = BankLayoutId("bpi.standard.v1")
    parser = FakeParser()
    router = StatementExtractionRouter(
        detector=FakeDetector(
            BankLayoutMatch(
                bank_id="bpi",
                layout_id=layout_id,
                detector_version="test-detector-v1",
                routing_evidence=("issuer-marker:bpi",),
            )
        ),
        parsers=ParserRegistry({layout_id: parser}),
    )

    result = router.extract((ExtractedPage(number=1, text="BPI statement"),))

    assert parser.calls == 1
    assert result.provenance == ExtractionProvenance(
        detector_version="test-detector-v1",
        detected_bank="bpi",
        layout_id="bpi.standard.v1",
        routing_evidence=("issuer-marker:bpi",),
        parser_id="test.parser",
        parser_version="test-parser-v1",
        extraction_strategy="deterministic",
        automatic_acceptance_eligible=True,
    )


def test_unknown_layout_is_rejected_without_a_model_fallback() -> None:
    router = StatementExtractionRouter(detector=FakeDetector(None), parsers=ParserRegistry({}))

    with pytest.raises(UnsupportedStatementLayoutError, match="unsupported statement layout"):
        router.extract((ExtractedPage(number=1, text="unknown statement"),))


def test_unregistered_layout_is_rejected_with_its_layout_id() -> None:
    router = StatementExtractionRouter(
        detector=FakeDetector(
            BankLayoutMatch(
                bank_id="bpi",
                layout_id=BankLayoutId("bpi.new-layout.v2"),
                detector_version="test-detector-v1",
                routing_evidence=("issuer-marker:bpi", "layout-marker:new"),
            )
        ),
        parsers=ParserRegistry({}),
    )

    with pytest.raises(UnsupportedStatementLayoutError, match="bpi.new-layout.v2"):
        router.extract((ExtractedPage(number=1, text="new layout"),))


def test_registry_rejects_a_non_deterministic_parser_entry() -> None:
    class MisconfiguredParser:
        parser_id = "misconfigured"
        parser_version = "1"
        extraction_strategy = "llm_fallback"

        def extract(self, pages: tuple[ExtractedPage, ...]) -> StatementExtraction:
            del pages
            return extraction()

    with pytest.raises(ValueError, match="deterministic extraction"):
        ParserRegistry(
            {BankLayoutId("bpi.misconfigured.v1"): cast(RegisteredParser, MisconfiguredParser())}
        )


def test_keyword_detector_returns_only_a_unique_verified_rule() -> None:
    detector = KeywordBankDetector(
        rules=(
            BankLayoutRule(
                bank_id="bpi",
                layout_id=BankLayoutId("bpi.standard.v1"),
                markers=("banco bpi", "movimentos"),
            ),
        )
    )

    match = detector.detect((ExtractedPage(number=1, text="BANCO BPI\nMOVIMENTOS"),))

    assert match is not None
    assert match.bank_id == "bpi"
    assert match.layout_id == BankLayoutId("bpi.standard.v1")
    assert match.routing_evidence == ("marker:banco bpi", "marker:movimentos")
