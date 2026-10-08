import logging

from bank_statement_assistant.statements.bpi import (
    BPI_INTEGRATED_LAYOUT,
    BPI_INTEGRATED_REQUIRED_MARKERS,
    BpiIntegratedStatementParser,
)
from bank_statement_assistant.statements.extraction import StatementExtractor
from bank_statement_assistant.statements.parser_registry import (
    BankLayoutRule,
    KeywordBankDetector,
    ParserRegistry,
    StatementExtractionRouter,
)

_logger = logging.getLogger(__name__)


def build_statement_extractor() -> StatementExtractor:
    parser = BpiIntegratedStatementParser()
    _logger.info(
        "statement_parser_registry_ready",
        extra={
            "parser_id": parser.parser_id,
            "parser_version": parser.parser_version,
            "extraction_strategy": parser.extraction_strategy,
        },
    )
    return StatementExtractionRouter(
        detector=KeywordBankDetector(
            rules=(
                BankLayoutRule(
                    bank_id="bpi",
                    layout_id=BPI_INTEGRATED_LAYOUT,
                    markers=BPI_INTEGRATED_REQUIRED_MARKERS,
                ),
            )
        ),
        parsers=ParserRegistry({BPI_INTEGRATED_LAYOUT: parser}),
    )
