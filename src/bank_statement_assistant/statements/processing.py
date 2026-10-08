from collections.abc import Callable, Mapping, Sequence
from logging import getLogger
from typing import Any, Protocol
from uuid import UUID

from pydantic import ValidationError

from bank_statement_assistant.jobs.models import ProcessingJob, ProcessingStage
from bank_statement_assistant.statements.classification import (
    CLASSIFICATION_PROMPT_VERSION,
    CLASSIFICATION_RULE_VERSION,
    CLASSIFICATION_TAXONOMY_VERSION,
    ClassificationDecision,
    ClassificationInput,
    ClassificationNormalization,
    TransactionClassifier,
    normalize_classification_result,
)
from bank_statement_assistant.statements.extraction import StatementExtraction, StatementExtractor
from bank_statement_assistant.statements.models import ExtractedPage, Statement
from bank_statement_assistant.statements.resolution import TransactionValues
from bank_statement_assistant.statements.validation import (
    VALIDATION_VERSION,
    validate_effective_balances,
    validate_extraction,
)

_logger = getLogger(__name__)


class StatementRepository(Protocol):
    def get(self, statement_id: UUID) -> Statement | None: ...

    def save_extracted_pages_and_enqueue(
        self,
        *,
        statement_id: UUID,
        pages: Sequence[ExtractedPage],
        predecessor_job_id: UUID,
        next_stage: ProcessingStage,
    ) -> Statement: ...

    def save_extraction_and_enqueue(
        self,
        *,
        statement_id: UUID,
        result: Mapping[str, Any],
        predecessor_job_id: UUID,
        next_stage: ProcessingStage,
    ) -> Statement: ...

    def save_validation_and_enqueue(
        self,
        *,
        statement_id: UUID,
        result: Mapping[str, Any],
        findings: Sequence[Mapping[str, Any]],
        predecessor_job_id: UUID,
        next_stage: ProcessingStage,
        correction_revision: int = 0,
    ) -> Statement: ...

    def publish_status(self, *, statement_id: UUID, ready: bool) -> Statement: ...

    def list_classification_inputs(
        self, *, statement_id: UUID
    ) -> Sequence[ClassificationInput]: ...

    def save_classifications_and_enqueue(
        self,
        *,
        statement_id: UUID,
        decisions: Sequence[ClassificationDecision],
        normalizations: Sequence[ClassificationNormalization] = (),
        provenance: Mapping[str, Any],
        predecessor_job_id: UUID,
        next_stage: ProcessingStage,
    ) -> Statement: ...

    def all_transactions_classified(self, *, statement_id: UUID) -> bool: ...

    def all_transactions_resolved(self, *, statement_id: UUID) -> bool: ...

    def list_effective_values(self, *, statement_id: UUID) -> Sequence[TransactionValues]: ...

    def current_correction_revision(self, *, statement_id: UUID) -> int: ...


class PdfTextExtractor(Protocol):
    def extract_text(self, *, content: bytes) -> Sequence[ExtractedPage]: ...


class StatementStageHandlers:
    def __init__(
        self,
        *,
        statements: StatementRepository,
        pdfs: PdfTextExtractor,
        extractor: StatementExtractor,
        classifier: TransactionClassifier,
        application_version: str = "unknown",
        classification_model: str = "unknown",
    ) -> None:
        self._statements = statements
        self._pdfs = pdfs
        self._extractor = extractor
        self._classifier = classifier
        self._application_version = application_version
        self._classification_model = classification_model

    def handlers(self) -> Mapping[ProcessingStage, Callable[[ProcessingJob], None]]:
        return {
            ProcessingStage.EXTRACT_TEXT: self._extract_text,
            ProcessingStage.EXTRACT_TRANSACTIONS: self._extract_transactions,
            ProcessingStage.VALIDATE: self._validate,
            ProcessingStage.REVALIDATE: self._revalidate,
            ProcessingStage.CLASSIFY: self._classify,
            ProcessingStage.REVIEW: self._review,
        }

    def _extract_text(self, job: ProcessingJob) -> None:
        statement = self._require_statement(job.statement_id)
        if statement.current_stage != ProcessingStage.EXTRACT_TEXT:
            return
        pages = tuple(self._pdfs.extract_text(content=statement.source_path.read_bytes()))
        self._statements.save_extracted_pages_and_enqueue(
            statement_id=statement.id,
            pages=pages,
            predecessor_job_id=job.id,
            next_stage=ProcessingStage.EXTRACT_TRANSACTIONS,
        )

    def _extract_transactions(self, job: ProcessingJob) -> None:
        statement = self._require_statement(job.statement_id)
        if statement.current_stage != ProcessingStage.EXTRACT_TRANSACTIONS:
            return
        extraction = self._extractor.extract(statement.extracted_pages)
        _logger.info(
            "statement_extracted",
            extra={
                "job_id": str(job.id),
                "statement_id": str(statement.id),
                "stage": job.stage.value,
                "parser_id": extraction.provenance.parser_id,
                "parser_version": extraction.provenance.parser_version,
                "extraction_strategy": extraction.provenance.extraction_strategy,
            },
        )
        self._statements.save_extraction_and_enqueue(
            statement_id=statement.id,
            result=extraction.model_dump(mode="json"),
            predecessor_job_id=job.id,
            next_stage=ProcessingStage.VALIDATE,
        )

    def _validate(self, job: ProcessingJob) -> None:
        statement = self._require_statement(job.statement_id)
        if statement.current_stage != ProcessingStage.VALIDATE:
            return
        if statement.extraction_result is None:
            raise ValueError("statement has no extraction result")
        extraction = StatementExtraction.model_validate(statement.extraction_result)
        validation = validate_extraction(extraction, pages=statement.extracted_pages)
        result = {
            "is_valid": validation.is_valid,
            "calculated_closing_balance": _decimal_string(validation.calculated_closing_balance),
            "difference": _decimal_string(validation.difference),
            "validation_version": VALIDATION_VERSION,
        }
        findings = [
            {
                "code": finding.code,
                "message": finding.message,
                "transaction_index": finding.transaction_index,
            }
            for finding in validation.findings
        ]
        self._statements.save_validation_and_enqueue(
            statement_id=statement.id,
            result=result,
            findings=findings,
            predecessor_job_id=job.id,
            next_stage=(
                ProcessingStage.CLASSIFY if validation.is_valid else ProcessingStage.REVIEW
            ),
        )

    def _revalidate(self, job: ProcessingJob) -> None:
        statement = self._require_statement(job.statement_id)
        if statement.current_stage != ProcessingStage.REVALIDATE:
            return
        if statement.extraction_result is None:
            raise ValueError("statement has no extraction result")
        extraction = StatementExtraction.model_validate(statement.extraction_result)
        correction_revision = self._statements.current_correction_revision(
            statement_id=statement.id
        )
        values = self._statements.list_effective_values(statement_id=statement.id)
        validation = validate_effective_balances(
            opening_balance=extraction.opening_balance,
            closing_balance=extraction.closing_balance,
            signed_amounts=tuple(value.signed_amount for value in values),
        )
        result = {
            "is_valid": validation.is_valid,
            "calculated_closing_balance": _decimal_string(validation.calculated_closing_balance),
            "difference": _decimal_string(validation.difference),
            "validation_version": VALIDATION_VERSION,
            "basis": "effective",
            "correction_revision": correction_revision,
        }
        findings = [
            {
                "code": finding.code,
                "message": finding.message,
                "transaction_index": finding.transaction_index,
            }
            for finding in validation.findings
        ]
        self._statements.save_validation_and_enqueue(
            statement_id=statement.id,
            result=result,
            findings=findings,
            predecessor_job_id=job.id,
            next_stage=ProcessingStage.REVIEW,
            correction_revision=correction_revision,
        )

    def _classify(self, job: ProcessingJob) -> None:
        statement = self._require_statement(job.statement_id)
        if statement.current_stage != ProcessingStage.CLASSIFY:
            return
        inputs = tuple(self._statements.list_classification_inputs(statement_id=statement.id))
        if not inputs:
            raise ValueError("statement has no transactions to classify")
        result = normalize_classification_result(self._classifier.classify(inputs))
        self._statements.save_classifications_and_enqueue(
            statement_id=statement.id,
            decisions=result.decisions,
            normalizations=result.normalizations,
            provenance={
                "application_version": self._application_version,
                "model": self._classification_model,
                "prompt_version": CLASSIFICATION_PROMPT_VERSION,
                "taxonomy_version": CLASSIFICATION_TAXONOMY_VERSION,
                "classification_rule_version": CLASSIFICATION_RULE_VERSION,
                "research": [
                    {
                        "source_ordinal": item.source_ordinal,
                        "status": item.status,
                        "provider": item.provider,
                        "query_hash": item.query_hash,
                        "response_hash": item.response_hash,
                        "source_count": item.source_count,
                        "cache_hit": item.cache_hit,
                        "pages_fetched": item.pages_fetched,
                        "escalation_reason": item.escalation_reason,
                        "fetched_at": (
                            item.fetched_at.isoformat() if item.fetched_at is not None else None
                        ),
                        "sources": [
                            {
                                "title": source.title,
                                "url": source.url,
                                "domain": source.domain,
                                "content_hash": source.content_hash,
                            }
                            for source in item.sources
                        ],
                    }
                    for item in result.research
                ],
            },
            predecessor_job_id=job.id,
            next_stage=ProcessingStage.REVIEW,
        )
        _logger.info(
            "statement_classified",
            extra={
                "job_id": str(job.id),
                "statement_id": str(statement.id),
                "stage": job.stage.value,
                "classification_count": len(result.decisions),
                "classification_normalization_count": len(result.normalizations),
                "prompt_version": CLASSIFICATION_PROMPT_VERSION,
                "taxonomy_version": CLASSIFICATION_TAXONOMY_VERSION,
            },
        )

    def _review(self, job: ProcessingJob) -> None:
        statement = self._require_statement(job.statement_id)
        if statement.current_stage != ProcessingStage.REVIEW:
            return
        validation = statement.validation_result
        extraction: StatementExtraction | None = None
        if statement.extraction_result is not None:
            try:
                extraction = StatementExtraction.model_validate(statement.extraction_result)
            except ValidationError:
                extraction = None
        ready = (
            validation is not None
            and validation.get("is_valid") is True
            and extraction is not None
            and extraction.provenance.automatic_acceptance_eligible
            and self._statements.all_transactions_resolved(statement_id=statement.id)
        )
        self._statements.publish_status(statement_id=statement.id, ready=ready)

    def _require_statement(self, statement_id: UUID) -> Statement:
        statement = self._statements.get(statement_id)
        if statement is None:
            raise LookupError(f"statement not found: {statement_id}")
        return statement


def _decimal_string(value: object) -> str | None:
    return None if value is None else str(value)
