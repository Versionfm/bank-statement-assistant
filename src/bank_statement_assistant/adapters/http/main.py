import uvicorn
from fastapi import FastAPI

from bank_statement_assistant.adapters.http.app import create_app
from bank_statement_assistant.adapters.postgres.health import PostgresReadiness
from bank_statement_assistant.adapters.postgres.statements import PostgresStatementRepository
from bank_statement_assistant.adapters.postgres.transactions import PostgresTransactionRepository
from bank_statement_assistant.config import Settings
from bank_statement_assistant.logging import configure_logging
from bank_statement_assistant.reporting.service import ReportingService
from bank_statement_assistant.statements.application import StatementApplication
from bank_statement_assistant.statements.files import LocalStatementFileStore
from bank_statement_assistant.statements.ingest import IngestStatement
from bank_statement_assistant.statements.pdf import SafePdfReader


def build_app() -> FastAPI:
    settings = Settings()  # type: ignore[call-arg]
    configure_logging(level=settings.log_level)
    repository = PostgresStatementRepository(settings.database_url)
    transaction_repository = PostgresTransactionRepository(settings.database_url)
    statement_application = StatementApplication(
        statements=repository,
        ingest=IngestStatement(
            statements=repository,
            files=LocalStatementFileStore(settings.statement_files_path),
            pdfs=SafePdfReader(
                max_bytes=settings.max_pdf_bytes,
                max_pages=settings.max_pdf_pages,
            ),
        ),
    )
    return create_app(
        readiness=PostgresReadiness(settings.database_url),
        statements=statement_application,
        transactions=transaction_repository,
        reporting=ReportingService(repository),
        static_files_path=settings.static_files_path,
        max_upload_bytes=settings.max_pdf_bytes,
    )


app = build_app()


def run() -> None:
    uvicorn.run(
        "bank_statement_assistant.adapters.http.main:app",
        host="0.0.0.0",
        port=8000,
    )


if __name__ == "__main__":
    run()
