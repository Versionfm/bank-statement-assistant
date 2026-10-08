import socket
import time
from hashlib import sha256

from bank_statement_assistant.adapters.browser_search import BrowserSearchEvidenceProvider
from bank_statement_assistant.adapters.postgres.health import SyncPostgresReadiness
from bank_statement_assistant.adapters.postgres.jobs import PostgresJobQueue
from bank_statement_assistant.adapters.postgres.merchant_evidence import (
    PostgresMerchantEvidenceCache,
)
from bank_statement_assistant.adapters.postgres.statements import PostgresStatementRepository
from bank_statement_assistant.adapters.web_search import WebSearchMerchantEvidenceProvider
from bank_statement_assistant.config import Settings
from bank_statement_assistant.jobs.models import ProcessingJob
from bank_statement_assistant.jobs.worker import Worker
from bank_statement_assistant.logging import configure_logging
from bank_statement_assistant.statements.classification import OpenAICompatibleTransactionClassifier
from bank_statement_assistant.statements.configured_parser import build_statement_extractor
from bank_statement_assistant.statements.merchant_evidence import (
    CachedMerchantEvidenceProvider,
    DisabledMerchantEvidenceProvider,
    MerchantEvidenceProvider,
    ResearchAwareTransactionClassifier,
)
from bank_statement_assistant.statements.pdf import SafePdfReader
from bank_statement_assistant.statements.processing import StatementStageHandlers


def run() -> None:
    settings = Settings()  # type: ignore[call-arg]
    configure_logging(level=settings.log_level)
    queue = PostgresJobQueue(
        settings.database_url,
        retry_delay_seconds=settings.job_retry_delay_seconds,
        max_attempts=settings.job_max_attempts,
        lease_seconds=settings.job_lease_seconds,
    )
    readiness = SyncPostgresReadiness(settings.database_url)
    statements = PostgresStatementRepository(settings.database_url)
    classifier = OpenAICompatibleTransactionClassifier(
        base_url=settings.inference_base_url,
        model=settings.inference_model,
        timeout_seconds=settings.inference_timeout_seconds,
        batch_size=settings.classification_batch_size,
    )
    evidence_provider: MerchantEvidenceProvider = DisabledMerchantEvidenceProvider()
    if settings.classification_research_enabled and settings.search_provider != "disabled":
        evidence_cache = PostgresMerchantEvidenceCache(settings.database_url)
        search_adapter: MerchantEvidenceProvider | None
        if settings.search_provider == "browser":
            search_adapter = BrowserSearchEvidenceProvider(
                base_url=settings.browser_search_base_url,
                timeout_seconds=settings.browser_search_timeout_seconds,
                max_results=settings.search_max_results,
                executable_path=settings.browser_search_executable_path,
            )
        elif settings.search_api_key:
            search_adapter = WebSearchMerchantEvidenceProvider(
                base_url=settings.search_base_url,
                api_key=settings.search_api_key,
                timeout_seconds=settings.search_timeout_seconds,
                max_results=settings.search_max_results,
            )
        else:
            search_adapter = None
        if search_adapter is not None:
            evidence_provider = CachedMerchantEvidenceProvider(
                cache=evidence_cache,
                lookup=search_adapter.lookup,
                ttl_seconds=settings.search_cache_ttl_seconds,
                cache_namespace=_search_cache_namespace(settings),
            )
    stage_handlers = StatementStageHandlers(
        statements=statements,
        pdfs=SafePdfReader(
            max_bytes=settings.max_pdf_bytes,
            max_pages=settings.max_pdf_pages,
        ),
        extractor=build_statement_extractor(),
        classifier=ResearchAwareTransactionClassifier(
            classifier=classifier,
            provider=evidence_provider,
            enabled=settings.classification_research_enabled,
        ),
        application_version=settings.application_version,
        classification_model=settings.inference_model,
    )

    def record_terminal_failure(original: ProcessingJob, result: ProcessingJob) -> None:
        if result.status == "failed":
            statements.mark_failed(
                statement_id=original.statement_id,
                error_code=result.last_error_code or f"{original.stage.value}_failed",
            )

    worker = Worker(
        queue=queue,
        worker_id=socket.gethostname(),
        handlers=stage_handlers.handlers(),
        handler_timeout_seconds=settings.job_handler_timeout_seconds,
        readiness=readiness.check,
        failure_observer=record_terminal_failure,
    )
    while True:
        if not worker.process_next():
            time.sleep(settings.worker_poll_seconds)


def _search_cache_namespace(settings: Settings) -> str:
    base_url = (
        settings.browser_search_base_url
        if settings.search_provider == "browser"
        else settings.search_base_url
    )
    fingerprint = f"{settings.search_provider}|{base_url}|{settings.search_max_results}"
    digest = sha256(fingerprint.encode("utf-8")).hexdigest()[:16]
    return f"{settings.search_provider}:{digest}"


if __name__ == "__main__":
    run()
