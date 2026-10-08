from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal, NewType, Protocol

from bank_statement_assistant.statements.extraction import StatementExtraction, StatementExtractor
from bank_statement_assistant.statements.models import ExtractedPage

BankLayoutId = NewType("BankLayoutId", str)


class UnsupportedStatementLayoutError(ValueError):
    """The statement is not a verified layout with a registered parser."""


@dataclass(frozen=True, slots=True)
class BankLayoutMatch:
    bank_id: str
    layout_id: BankLayoutId
    detector_version: str
    routing_evidence: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class BankLayoutRule:
    bank_id: str
    layout_id: BankLayoutId
    markers: tuple[str, ...]


class BankDetector(Protocol):
    @property
    def version(self) -> str: ...

    def detect(self, pages: Sequence[ExtractedPage]) -> BankLayoutMatch | None: ...


class RegisteredParser(StatementExtractor, Protocol):
    @property
    def extraction_strategy(self) -> Literal["deterministic"]: ...

    @property
    def parser_id(self) -> str: ...

    @property
    def parser_version(self) -> str: ...


class KeywordBankDetector:
    """Conservatively identify a verified layout from all required markers."""

    version = "keyword-v1"

    def __init__(self, *, rules: Sequence[BankLayoutRule]) -> None:
        self._rules = tuple(rules)
        for rule in self._rules:
            if not rule.markers:
                raise ValueError("bank layout rules must contain at least one marker")

    def detect(self, pages: Sequence[ExtractedPage]) -> BankLayoutMatch | None:
        source = "\n".join(page.text.casefold() for page in pages)
        matches = tuple(
            rule
            for rule in self._rules
            if all(marker.casefold() in source for marker in rule.markers)
        )
        if len(matches) != 1:
            return None
        rule = matches[0]
        return BankLayoutMatch(
            bank_id=rule.bank_id,
            layout_id=rule.layout_id,
            detector_version=self.version,
            routing_evidence=tuple(f"marker:{marker.casefold()}" for marker in rule.markers),
        )


class ParserRegistry:
    def __init__(self, parsers: Mapping[BankLayoutId, RegisteredParser]) -> None:
        self._parsers = dict(parsers)
        for layout_id, parser in self._parsers.items():
            if not layout_id:
                raise ValueError("bank layout IDs must be non-empty")
            self._validate_parser_identity(parser)

    def resolve(self, layout_id: BankLayoutId) -> RegisteredParser | None:
        return self._parsers.get(layout_id)

    @staticmethod
    def _validate_parser_identity(parser: RegisteredParser) -> None:
        if getattr(parser, "extraction_strategy", None) != "deterministic":
            raise ValueError("registered parsers must declare deterministic extraction")
        for name in ("parser_id", "parser_version"):
            value = getattr(parser, name, None)
            if not isinstance(value, str) or not value:
                raise ValueError(f"registered parsers must expose a non-empty {name}")


class StatementExtractionRouter:
    """Route only to registered deterministic parsers; never invoke a model."""

    def __init__(self, *, detector: BankDetector, parsers: ParserRegistry) -> None:
        self._detector = detector
        self._parsers = parsers

    def extract(self, pages: Sequence[ExtractedPage]) -> StatementExtraction:
        match = self._detector.detect(pages)
        if match is None:
            raise UnsupportedStatementLayoutError("unsupported statement layout")
        parser = self._parsers.resolve(match.layout_id)
        if parser is None:
            raise UnsupportedStatementLayoutError(
                f"unsupported statement layout: {match.layout_id}"
            )
        extraction = parser.extract(pages)
        return extraction.model_copy(
            update={
                "provenance": extraction.provenance.model_copy(
                    update={
                        "detector_version": match.detector_version,
                        "detected_bank": match.bank_id,
                        "layout_id": str(match.layout_id),
                        "routing_evidence": match.routing_evidence,
                        "parser_id": parser.parser_id,
                        "parser_version": parser.parser_version,
                        "extraction_strategy": "deterministic",
                        "automatic_acceptance_eligible": True,
                    }
                )
            }
        )
