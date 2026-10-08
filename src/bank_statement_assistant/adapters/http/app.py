from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Any, Literal, Protocol
from uuid import UUID

from fastapi import FastAPI, File, Form, HTTPException, Query, Response, UploadFile, status
from fastapi import Path as FastAPIPath
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from bank_statement_assistant.config import APPLICATION_VERSION
from bank_statement_assistant.jobs.models import ProcessingStage
from bank_statement_assistant.reporting.models import (
    MonthlyReport,
    ReportDrilldownQuery,
    ReportGroup,
    ReportOverview,
    ReportQuery,
    ReportResult,
    ReportTotals,
    ReportTransactionPage,
)
from bank_statement_assistant.statements.classification import (
    ClassificationStatus,
    MovementKind,
    PaymentChannel,
    ReportingCategory,
    TransferScope,
)
from bank_statement_assistant.statements.models import IngestResult, Statement
from bank_statement_assistant.statements.resolution import (
    ClassificationAcceptance,
    CorrectionCommand,
    CorrectionRecord,
    ResolutionConflictError,
    ResolutionError,
    ResolutionNotFoundError,
    RevertCommand,
)
from bank_statement_assistant.statements.transactions import (
    Transaction,
    TransactionFilters,
    TransactionPage,
    TransactionSort,
)


class HealthResponse(BaseModel):
    status: Literal["ok", "unavailable"]


class Readiness(Protocol):
    """Dependency readiness observed by the HTTP adapter."""

    async def check(self) -> bool: ...


class StatementsApplication(Protocol):
    def ingest(
        self,
        *,
        account_reference: str,
        original_filename: str,
        content: bytes,
    ) -> IngestResult: ...

    def list(self) -> tuple[Statement, ...]: ...

    def get(self, statement_id: UUID) -> Statement | None: ...

    def retry(self, statement_id: UUID) -> Statement | None: ...

    def reprocess_from_source(self, statement_id: UUID) -> Statement | None: ...


class TransactionsApplication(Protocol):
    def list(self, *, filters: TransactionFilters) -> TransactionPage: ...

    def get(self, transaction_id: UUID) -> Transaction | None: ...

    def correct(self, transaction_id: UUID, command: CorrectionCommand) -> Transaction: ...

    def history(self, transaction_id: UUID) -> tuple[CorrectionRecord, ...]: ...

    def revert(self, transaction_id: UUID, command: RevertCommand) -> Transaction: ...

    def accept_classification(
        self, transaction_id: UUID, acceptance: ClassificationAcceptance
    ) -> Transaction: ...


class ReportingApplication(Protocol):
    def report(self, query: ReportQuery) -> ReportResult: ...

    def drilldown(
        self, query: ReportQuery, drilldown: ReportDrilldownQuery
    ) -> ReportTransactionPage: ...


class StatementResponse(BaseModel):
    id: UUID
    account_reference: str
    original_filename: str
    page_count: int
    status: Literal["processing", "needs_review", "ready", "failed", "archived"]
    current_stage: ProcessingStage
    extraction_result: dict[str, Any] | None
    validation_result: dict[str, Any] | None
    review_findings: list[dict[str, Any]]
    last_error_code: str | None
    created_at: datetime | None


class TransactionResponse(BaseModel):
    id: UUID
    statement_id: UUID
    statement_filename: str
    statement_status: Literal["processing", "needs_review", "ready", "failed", "archived"]
    source_ordinal: int
    booking_date: date
    description: str
    signed_amount: str
    currency: str
    confidence: float
    evidence_page_number: int | None
    evidence_line_start: int | None
    evidence_line_end: int | None
    evidence_quote: str | None
    reporting_category: str | None
    movement_kind: str | None
    payment_channel: str | None
    counterparty: str | None = None
    note: str | None = None
    classification_status: str
    classification_confidence: float | None
    classification_provenance: dict[str, object] | None
    review_findings: list[dict[str, str]]
    classification_id: int | None = None
    classification_resolution: Literal["pending", "accepted", "corrected"] = "pending"
    transfer_scope: TransferScope | None = None
    correction_revision: int = 0
    original_booking_date: date | None = None
    original_description: str | None = None
    original_signed_amount: str | None = None
    original_currency: str | None = None
    original_reporting_category: str | None = None
    original_movement_kind: str | None = None
    original_payment_channel: str | None = None
    original_counterparty: str | None = None
    original_note: str | None = None
    original_transfer_scope: TransferScope | None = None


class TransactionCorrectionRequest(BaseModel):
    expected_revision: int = 0
    reason: str
    idempotency_key: str
    booking_date: date | None = None
    description: str | None = None
    signed_amount: Decimal | None = None
    currency: str | None = None
    reporting_category: ReportingCategory | None = None
    movement_kind: MovementKind | None = None
    payment_channel: PaymentChannel | None = None
    counterparty: str | None = None
    note: str | None = None
    transfer_scope: TransferScope | None = None

    def changes(self) -> dict[str, object]:
        return self.model_dump(
            exclude_unset=True,
            exclude={"expected_revision", "reason", "idempotency_key"},
        )


class TransactionRevertRequest(BaseModel):
    expected_revision: int = 0
    target_revision: int
    reason: str
    idempotency_key: str


class ClassificationAcceptanceRequest(BaseModel):
    classification_id: int
    idempotency_key: str
    reason: str | None = None


class TransactionValuesResponse(BaseModel):
    booking_date: date
    description: str
    signed_amount: str
    currency: str
    reporting_category: str | None
    movement_kind: str | None
    payment_channel: str | None
    counterparty: str | None
    note: str | None
    transfer_scope: TransferScope | None


class CorrectionRecordResponse(BaseModel):
    id: UUID
    transaction_id: UUID
    revision: int
    previous_revision: int
    values: TransactionValuesResponse
    reason: str
    origin: str
    created_at: datetime | None


class TransactionPageResponse(BaseModel):
    items: list[TransactionResponse]
    total: int
    limit: int
    offset: int


class ReportTotalsResponse(BaseModel):
    income: str
    gross_spending: str
    refunds: str
    net_spending: str
    net_cash_flow: str
    transfer_in: str
    transfer_out: str
    net_account_flow: str


class BreakdownItemResponse(BaseModel):
    label: str
    amount: str
    transaction_count: int


class ReportQualityResponse(BaseModel):
    is_provisional: bool
    provisional_count: int
    unresolved_count: int
    unresolved_amount: str


class TransferSummaryResponse(BaseModel):
    count: int
    total: str
    incoming: str
    outgoing: str
    own_account_total: str
    external_total: str
    unknown_total: str


class LargestTransactionResponse(BaseModel):
    id: UUID
    booking_date: date
    description: str
    amount: str
    currency: str
    counterparty: str | None
    reporting_category: str | None


class MonthlyReportResponse(BaseModel):
    month: str
    totals: ReportTotalsResponse
    category_breakdown: list[BreakdownItemResponse]
    counterparty_breakdown: list[BreakdownItemResponse]
    payment_channel_breakdown: list[BreakdownItemResponse]
    largest_transactions: list[LargestTransactionResponse]
    transfers: TransferSummaryResponse
    quality: ReportQualityResponse


class ReportOverviewResponse(BaseModel):
    totals: ReportTotalsResponse
    previous_period_change: str | None


class CurrencySummaryResponse(BaseModel):
    currency: str
    amount: str
    transaction_count: int


class ReportResponse(BaseModel):
    overview: ReportOverviewResponse
    months: list[MonthlyReportResponse]
    non_eur: list[CurrencySummaryResponse]
    non_eur_transactions: list[LargestTransactionResponse]


class ReportTransactionResponse(BaseModel):
    id: UUID
    booking_date: date
    description: str
    signed_amount: str
    currency: str
    reporting_category: str | None
    movement_kind: str | None
    payment_channel: str | None
    counterparty: str | None
    transfer_scope: TransferScope | None


class ReportTransactionPageResponse(BaseModel):
    items: list[ReportTransactionResponse]
    total: int
    limit: int
    offset: int


def create_app(
    *,
    readiness: Readiness,
    statements: StatementsApplication | None = None,
    transactions: TransactionsApplication | None = None,
    reporting: ReportingApplication | None = None,
    static_files_path: Path | None = None,
    max_upload_bytes: int = 15 * 1024 * 1024,
) -> FastAPI:
    if max_upload_bytes < 1:
        raise ValueError("max_upload_bytes must be positive")
    statement_application = statements or _UnavailableStatements()
    transaction_application = transactions or _UnavailableTransactions()
    reporting_application = reporting or _UnavailableReporting()
    app = FastAPI(
        title="Bank Statement Assistant",
        version=APPLICATION_VERSION,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )

    @app.get("/api/health/live", tags=["health"], response_model=HealthResponse)
    async def liveness() -> HealthResponse:
        return HealthResponse(status="ok")

    @app.get(
        "/api/health/ready",
        tags=["health"],
        response_model=HealthResponse,
        responses={
            status.HTTP_503_SERVICE_UNAVAILABLE: {
                "description": "Dependency unavailable",
                "model": HealthResponse,
            }
        },
    )
    async def dependency_readiness() -> JSONResponse:
        if await readiness.check():
            return JSONResponse(content={"status": "ok"})
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "unavailable"},
        )

    @app.post(
        "/api/statements",
        tags=["statements"],
        response_model=StatementResponse,
        status_code=status.HTTP_201_CREATED,
        responses={status.HTTP_200_OK: {"model": StatementResponse}},
    )
    async def upload_statement(
        response: Response,
        account_reference: Annotated[str, Form()],
        file: Annotated[UploadFile, File()],
    ) -> StatementResponse:
        content = await _read_bounded(file, max_bytes=max_upload_bytes)
        try:
            result = statement_application.ingest(
                account_reference=account_reference,
                original_filename=file.filename or "",
                content=content,
            )
        except ValueError as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(error),
            ) from error
        if not result.created:
            response.status_code = status.HTTP_200_OK
        return _statement_response(result.statement)

    @app.get(
        "/api/statements",
        tags=["statements"],
        response_model=list[StatementResponse],
    )
    async def list_statements() -> list[StatementResponse]:
        return [_statement_response(statement) for statement in statement_application.list()]

    @app.get(
        "/api/statements/{statement_id}",
        tags=["statements"],
        response_model=StatementResponse,
    )
    async def get_statement(statement_id: UUID) -> StatementResponse:
        statement = statement_application.get(statement_id)
        if statement is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        return _statement_response(statement)

    @app.post(
        "/api/statements/{statement_id}/retry",
        tags=["statements"],
        response_model=StatementResponse,
    )
    async def retry_statement(statement_id: UUID) -> StatementResponse:
        statement = statement_application.retry(statement_id)
        if statement is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        return _statement_response(statement)

    @app.post(
        "/api/statements/{statement_id}/reprocess",
        tags=["statements"],
        response_model=StatementResponse,
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def reprocess_statement(statement_id: UUID) -> StatementResponse:
        statement = statement_application.reprocess_from_source(statement_id)
        if statement is not None:
            return _statement_response(statement)
        if statement_application.get(statement_id) is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Statement cannot be reprocessed from its source in its current state",
        )

    @app.get(
        "/api/transactions",
        tags=["transactions"],
        response_model=TransactionPageResponse,
        response_model_exclude_defaults=True,
    )
    async def list_transactions(
        statement_id: UUID | None = None,
        review_only: bool = False,
        booking_date_from: date | None = None,
        booking_date_to: date | None = None,
        description: Annotated[str | None, Query(max_length=200)] = None,
        amount_min: Annotated[Decimal | None, Query(ge=0)] = None,
        amount_max: Annotated[Decimal | None, Query(ge=0)] = None,
        movement_kind: MovementKind | None = None,
        money_direction: Literal["in", "out"] | None = None,
        classification_status: ClassificationStatus | None = None,
        payment_channel: PaymentChannel | None = None,
        transfer_scope: TransferScope | None = None,
        reporting_category: ReportingCategory | None = None,
        currency: Annotated[str | None, Query(min_length=3, max_length=3)] = None,
        sort: TransactionSort = "booking_date",
        direction: Literal["asc", "desc"] = "desc",
        limit: int = Query(default=50, ge=1, le=50),
        offset: int = Query(default=0, ge=0),
    ) -> TransactionPageResponse:
        if (
            booking_date_from is not None
            and booking_date_to is not None
            and booking_date_from > booking_date_to
        ):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="booking_date_from must not be after booking_date_to",
            )
        if amount_min is not None and amount_max is not None and amount_min > amount_max:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="amount_min must not be greater than amount_max",
            )
        page = transaction_application.list(
            filters=TransactionFilters(
                statement_id=statement_id,
                review_only=review_only,
                booking_date_from=booking_date_from,
                booking_date_to=booking_date_to,
                description_query=(
                    description.strip() if description and description.strip() else None
                ),
                amount_min=amount_min,
                amount_max=amount_max,
                movement_kind=movement_kind,
                money_direction=money_direction,
                classification_status=classification_status,
                payment_channel=payment_channel,
                transfer_scope=transfer_scope,
                reporting_category=reporting_category,
                currency=currency.upper() if currency else None,
                sort=sort,
                descending=direction == "desc",
                limit=limit,
                offset=offset,
            )
        )
        return _transaction_page_response(page)

    @app.get("/api/reports", tags=["reports"], response_model=ReportResponse)
    async def get_report(
        month_from: Annotated[str | None, Query(pattern=r"^\d{4}-\d{2}$")] = None,
        month_to: Annotated[str | None, Query(pattern=r"^\d{4}-\d{2}$")] = None,
        statement_id: UUID | None = None,
        currency: Annotated[str, Query(min_length=3, max_length=3)] = "EUR",
        reporting_category: ReportingCategory | None = None,
        movement_kind: MovementKind | None = None,
        payment_channel: PaymentChannel | None = None,
        counterparty: Annotated[str | None, Query(max_length=200)] = None,
        include_provisional: bool = True,
    ) -> ReportResponse:
        currency = currency.upper()
        if month_from and month_to and month_from > month_to:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="month_from must not be after month_to",
            )
        result = reporting_application.report(
            ReportQuery(
                month_from=month_from,
                month_to=month_to,
                statement_id=statement_id,
                currency=currency,
                reporting_category=reporting_category,
                movement_kind=movement_kind,
                payment_channel=payment_channel,
                counterparty=counterparty.strip() if counterparty else None,
                include_provisional=include_provisional,
            )
        )
        return _report_response(result)

    @app.get(
        "/api/reports/transactions",
        tags=["reports"],
        response_model=ReportTransactionPageResponse,
    )
    async def get_report_transactions(
        group: ReportGroup,
        value: Annotated[str, Query(min_length=1, max_length=200)],
        month_from: Annotated[str | None, Query(pattern=r"^\d{4}-\d{2}$")] = None,
        month_to: Annotated[str | None, Query(pattern=r"^\d{4}-\d{2}$")] = None,
        statement_id: UUID | None = None,
        currency: Annotated[str, Query(min_length=3, max_length=3)] = "EUR",
        reporting_category: ReportingCategory | None = None,
        movement_kind: MovementKind | None = None,
        payment_channel: PaymentChannel | None = None,
        counterparty: Annotated[str | None, Query(max_length=200)] = None,
        include_provisional: bool = True,
        limit: int = Query(default=50, ge=1, le=100),
        offset: int = Query(default=0, ge=0),
    ) -> ReportTransactionPageResponse:
        if month_from and month_to and month_from > month_to:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="month_from must not be after month_to",
            )
        page = reporting_application.drilldown(
            ReportQuery(
                month_from=month_from,
                month_to=month_to,
                statement_id=statement_id,
                currency=currency.upper(),
                reporting_category=reporting_category,
                movement_kind=movement_kind,
                payment_channel=payment_channel,
                counterparty=counterparty.strip() if counterparty else None,
                include_provisional=include_provisional,
            ),
            ReportDrilldownQuery(group=group, value=value, limit=limit, offset=offset),
        )
        return _report_transaction_page_response(page)

    @app.get(
        "/api/reports/months/{month}",
        tags=["reports"],
        response_model=MonthlyReportResponse,
    )
    async def get_month_report(
        month: Annotated[str, FastAPIPath(pattern=r"^\d{4}-\d{2}$")],
        statement_id: UUID | None = None,
        currency: Annotated[str, Query(min_length=3, max_length=3)] = "EUR",
        reporting_category: ReportingCategory | None = None,
        movement_kind: MovementKind | None = None,
        payment_channel: PaymentChannel | None = None,
        counterparty: Annotated[str | None, Query(max_length=200)] = None,
        include_provisional: bool = True,
    ) -> MonthlyReportResponse:
        result = reporting_application.report(
            ReportQuery(
                month_from=month,
                month_to=month,
                statement_id=statement_id,
                currency=currency.upper(),
                reporting_category=reporting_category,
                movement_kind=movement_kind,
                payment_channel=payment_channel,
                counterparty=counterparty.strip() if counterparty else None,
                include_provisional=include_provisional,
            )
        )
        if not result.months:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Report month not found",
            )
        return _monthly_report_response(result.months[0])

    @app.get(
        "/api/transactions/{transaction_id}",
        tags=["transactions"],
        response_model=TransactionResponse,
        response_model_exclude_defaults=True,
    )
    async def get_transaction(transaction_id: UUID) -> TransactionResponse:
        transaction = transaction_application.get(transaction_id)
        if transaction is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        return _transaction_response(transaction)

    @app.post(
        "/api/transactions/{transaction_id}/corrections",
        tags=["transactions"],
        response_model=TransactionResponse,
        response_model_exclude_defaults=True,
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def correct_transaction(
        transaction_id: UUID, request: TransactionCorrectionRequest
    ) -> TransactionResponse:
        try:
            transaction = transaction_application.correct(
                transaction_id,
                CorrectionCommand(
                    expected_revision=request.expected_revision,
                    changes=request.changes(),
                    reason=request.reason,
                    idempotency_key=request.idempotency_key,
                ),
            )
        except ResolutionNotFoundError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
        except ResolutionConflictError as error:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
        except ResolutionError as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)
            ) from error
        return _transaction_response(transaction)

    @app.get(
        "/api/transactions/{transaction_id}/history",
        tags=["transactions"],
        response_model=list[CorrectionRecordResponse],
    )
    async def transaction_history(transaction_id: UUID) -> list[CorrectionRecordResponse]:
        if transaction_application.get(transaction_id) is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        return [
            _correction_record_response(record)
            for record in transaction_application.history(transaction_id)
        ]

    @app.post(
        "/api/transactions/{transaction_id}/revert",
        tags=["transactions"],
        response_model=TransactionResponse,
        response_model_exclude_defaults=True,
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def revert_transaction(
        transaction_id: UUID, request: TransactionRevertRequest
    ) -> TransactionResponse:
        try:
            transaction = transaction_application.revert(
                transaction_id,
                RevertCommand(
                    expected_revision=request.expected_revision,
                    target_revision=request.target_revision,
                    reason=request.reason,
                    idempotency_key=request.idempotency_key,
                ),
            )
        except ResolutionNotFoundError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
        except ResolutionConflictError as error:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
        except ResolutionError as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)
            ) from error
        return _transaction_response(transaction)

    @app.post(
        "/api/transactions/{transaction_id}/classification/accept",
        tags=["transactions"],
        response_model=TransactionResponse,
        response_model_exclude_defaults=True,
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def accept_classification(
        transaction_id: UUID, request: ClassificationAcceptanceRequest
    ) -> TransactionResponse:
        try:
            transaction = transaction_application.accept_classification(
                transaction_id,
                ClassificationAcceptance(
                    classification_id=request.classification_id,
                    reason=request.reason,
                    idempotency_key=request.idempotency_key,
                ),
            )
        except ResolutionNotFoundError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
        except ResolutionConflictError as error:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
        except ResolutionError as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)
            ) from error
        return _transaction_response(transaction)

    if static_files_path is not None:
        app.mount("/", StaticFiles(directory=static_files_path, html=True), name="frontend")

    return app


class _UnavailableStatements:
    def ingest(
        self,
        *,
        account_reference: str,
        original_filename: str,
        content: bytes,
    ) -> IngestResult:
        raise ValueError("statement ingestion is unavailable")

    def list(self) -> tuple[Statement, ...]:
        return ()

    def get(self, statement_id: UUID) -> Statement | None:
        return None

    def retry(self, statement_id: UUID) -> Statement | None:
        return None

    def reprocess_from_source(self, statement_id: UUID) -> Statement | None:
        return None


class _UnavailableTransactions:
    def list(self, *, filters: TransactionFilters) -> TransactionPage:
        return TransactionPage(items=(), total=0, limit=filters.limit, offset=filters.offset)

    def get(self, transaction_id: UUID) -> Transaction | None:
        return None

    def correct(self, transaction_id: UUID, command: CorrectionCommand) -> Transaction:
        raise ResolutionNotFoundError("transaction application is unavailable")

    def history(self, transaction_id: UUID) -> tuple[CorrectionRecord, ...]:
        raise ResolutionNotFoundError("transaction application is unavailable")

    def revert(self, transaction_id: UUID, command: RevertCommand) -> Transaction:
        raise ResolutionNotFoundError("transaction application is unavailable")

    def accept_classification(
        self, transaction_id: UUID, acceptance: ClassificationAcceptance
    ) -> Transaction:
        raise ResolutionNotFoundError("transaction application is unavailable")


class _UnavailableReporting:
    def report(self, query: ReportQuery) -> ReportResult:
        return ReportResult(
            overview=ReportOverview(totals=ReportTotals(), previous_period_change=None),
            months=(),
            non_eur=(),
        )

    def drilldown(
        self, query: ReportQuery, drilldown: ReportDrilldownQuery
    ) -> ReportTransactionPage:
        return ReportTransactionPage(
            items=(), total=0, limit=drilldown.limit, offset=drilldown.offset
        )


def _statement_response(statement: Statement) -> StatementResponse:
    return StatementResponse(
        id=statement.id,
        account_reference=statement.account_reference,
        original_filename=statement.original_filename,
        page_count=statement.page_count,
        status=statement.status,
        current_stage=statement.current_stage,
        extraction_result=statement.extraction_result,
        validation_result=statement.validation_result,
        review_findings=list(statement.review_findings),
        last_error_code=statement.last_error_code,
        created_at=statement.created_at,
    )


def _transaction_page_response(page: TransactionPage) -> TransactionPageResponse:
    return TransactionPageResponse(
        items=[_transaction_response(transaction) for transaction in page.items],
        total=page.total,
        limit=page.limit,
        offset=page.offset,
    )


def _transaction_response(transaction: Transaction) -> TransactionResponse:
    original = transaction.original_values
    return TransactionResponse(
        id=transaction.id,
        statement_id=transaction.statement_id,
        statement_filename=transaction.statement_filename,
        statement_status=transaction.statement_status,
        source_ordinal=transaction.source_ordinal,
        booking_date=transaction.booking_date,
        description=transaction.description,
        signed_amount=_decimal_text(transaction.signed_amount),
        currency=transaction.currency,
        confidence=transaction.confidence,
        evidence_page_number=transaction.evidence_page_number,
        evidence_line_start=transaction.evidence_line_start,
        evidence_line_end=transaction.evidence_line_end,
        evidence_quote=transaction.evidence_quote,
        reporting_category=transaction.reporting_category,
        movement_kind=transaction.movement_kind,
        payment_channel=transaction.payment_channel,
        counterparty=transaction.counterparty,
        note=transaction.note,
        classification_status=transaction.classification_status,
        classification_confidence=transaction.classification_confidence,
        classification_provenance=transaction.classification_provenance,
        review_findings=list(transaction.review_findings),
        classification_id=transaction.classification_id,
        classification_resolution=transaction.classification_resolution,
        correction_revision=transaction.correction_revision,
        original_booking_date=None if original is None else original.booking_date,
        original_description=None if original is None else original.description,
        original_signed_amount=(
            None if original is None else _decimal_text(original.signed_amount)
        ),
        original_currency=None if original is None else original.currency,
        original_reporting_category=(None if original is None else original.reporting_category),
        original_movement_kind=None if original is None else original.movement_kind,
        original_payment_channel=None if original is None else original.payment_channel,
        original_counterparty=None if original is None else original.counterparty,
        original_note=None if original is None else original.note,
        original_transfer_scope=None if original is None else original.transfer_scope,
    )


def _correction_record_response(record: CorrectionRecord) -> CorrectionRecordResponse:
    values = record.correction.values
    return CorrectionRecordResponse(
        id=record.id,
        transaction_id=record.transaction_id,
        revision=record.correction.revision,
        previous_revision=record.correction.previous_revision,
        values=TransactionValuesResponse(
            booking_date=values.booking_date,
            description=values.description,
            signed_amount=_decimal_text(values.signed_amount),
            currency=values.currency,
            reporting_category=values.reporting_category,
            movement_kind=values.movement_kind,
            payment_channel=values.payment_channel,
            counterparty=values.counterparty,
            note=values.note,
            transfer_scope=values.transfer_scope,
        ),
        reason=record.reason,
        origin=record.origin,
        created_at=record.created_at,
    )


def _decimal_text(value: Decimal) -> str:
    rendered = format(value, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return "0" if rendered in {"", "-0"} else rendered


def _report_response(result: ReportResult) -> ReportResponse:
    return ReportResponse(
        overview=ReportOverviewResponse(
            totals=_totals_response(result.overview.totals),
            previous_period_change=(
                None
                if result.overview.previous_period_change is None
                else _decimal_text(result.overview.previous_period_change)
            ),
        ),
        months=[_monthly_report_response(month) for month in result.months],
        non_eur=[
            CurrencySummaryResponse(
                currency=item.currency,
                amount=_decimal_text(item.amount),
                transaction_count=item.transaction_count,
            )
            for item in result.non_eur
        ],
        non_eur_transactions=[
            LargestTransactionResponse(
                id=item.id,
                booking_date=item.booking_date,
                description=item.description,
                amount=_decimal_text(item.amount),
                currency=item.currency,
                counterparty=item.counterparty,
                reporting_category=item.reporting_category,
            )
            for item in result.non_eur_transactions
        ],
    )


def _totals_response(totals: Any) -> ReportTotalsResponse:
    return ReportTotalsResponse(
        income=_decimal_text(totals.income),
        gross_spending=_decimal_text(totals.gross_spending),
        refunds=_decimal_text(totals.refunds),
        net_spending=_decimal_text(totals.net_spending),
        net_cash_flow=_decimal_text(totals.net_cash_flow),
        transfer_in=_decimal_text(totals.transfer_in),
        transfer_out=_decimal_text(totals.transfer_out),
        net_account_flow=_decimal_text(totals.net_account_flow),
    )


def _monthly_report_response(month: MonthlyReport) -> MonthlyReportResponse:
    return MonthlyReportResponse(
        month=month.month,
        totals=_totals_response(month.totals),
        category_breakdown=[_breakdown_response(item) for item in month.category_breakdown],
        counterparty_breakdown=[
            _breakdown_response(item) for item in month.counterparty_breakdown
        ],
        payment_channel_breakdown=[
            _breakdown_response(item) for item in month.payment_channel_breakdown
        ],
        largest_transactions=[
            LargestTransactionResponse(
                id=item.id,
                booking_date=item.booking_date,
                description=item.description,
                amount=_decimal_text(item.amount),
                currency=item.currency,
                counterparty=item.counterparty,
                reporting_category=item.reporting_category,
            )
            for item in month.largest_transactions
        ],
        transfers=TransferSummaryResponse(
            count=month.transfers.count,
            total=_decimal_text(month.transfers.total),
            incoming=_decimal_text(month.transfers.incoming),
            outgoing=_decimal_text(month.transfers.outgoing),
            own_account_total=_decimal_text(month.transfers.own_account_total),
            external_total=_decimal_text(month.transfers.external_total),
            unknown_total=_decimal_text(month.transfers.unknown_total),
        ),
        quality=ReportQualityResponse(
            is_provisional=month.quality.is_provisional,
            provisional_count=month.quality.provisional_count,
            unresolved_count=month.quality.unresolved_count,
            unresolved_amount=_decimal_text(month.quality.unresolved_amount),
        ),
    )


def _breakdown_response(item: Any) -> BreakdownItemResponse:
    return BreakdownItemResponse(
        label=item.label,
        amount=_decimal_text(item.amount),
        transaction_count=item.transaction_count,
    )


def _report_transaction_page_response(
    page: ReportTransactionPage,
) -> ReportTransactionPageResponse:
    return ReportTransactionPageResponse(
        items=[
            ReportTransactionResponse(
                id=item.id,
                booking_date=item.booking_date,
                description=item.description,
                signed_amount=_decimal_text(item.signed_amount),
                currency=item.currency,
                reporting_category=item.reporting_category,
                movement_kind=item.movement_kind,
                payment_channel=item.payment_channel,
                counterparty=item.counterparty,
                transfer_scope=item.transfer_scope,
            )
            for item in page.items
        ],
        total=page.total,
        limit=page.limit,
        offset=page.offset,
    )


async def _read_bounded(file: UploadFile, *, max_bytes: int) -> bytes:
    chunks: list[bytes] = []
    size = 0
    while True:
        chunk = await file.read(min(1024 * 1024, max_bytes - size + 1))
        if not chunk:
            return b"".join(chunks)
        size += len(chunk)
        if size > max_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail="PDF exceeds the upload limit",
            )
        chunks.append(chunk)
