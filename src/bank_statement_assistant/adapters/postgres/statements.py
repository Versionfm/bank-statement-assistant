import json
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, cast
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import RowMapping

from bank_statement_assistant.jobs.models import ProcessingStage
from bank_statement_assistant.reporting.models import ReportTransaction
from bank_statement_assistant.statements.classification import (
    ClassificationDecision,
    ClassificationInput,
    ClassificationNormalization,
    ClassificationStatus,
    MovementKind,
    PaymentChannel,
    ReportingCategory,
    TransferScope,
)
from bank_statement_assistant.statements.extraction import TransactionCandidate
from bank_statement_assistant.statements.models import ExtractedPage, Statement, StatementStatus
from bank_statement_assistant.statements.resolution import (
    ClassificationAcceptance,
    ClassificationResolution,
    CorrectionCommand,
    CorrectionRecord,
    ResolutionConflictError,
    ResolutionError,
    ResolutionNotFoundError,
    RevertCommand,
    TransactionCorrection,
    TransactionValues,
    correction_from_values,
)
from bank_statement_assistant.statements.transactions import (
    Transaction,
    TransactionFilters,
    TransactionPage,
)


class PostgresStatementRepository:
    def __init__(self, database_url: str) -> None:
        self._engine: Engine = create_engine(
            database_url,
            pool_pre_ping=True,
            connect_args={"connect_timeout": 5, "options": "-c statement_timeout=5000"},
        )

    def dispose(self) -> None:
        self._engine.dispose()

    def find_by_content_hash(self, content_hash: str) -> Statement | None:
        return self._one_or_none(
            "SELECT * FROM statements WHERE content_hash = :content_hash",
            {"content_hash": content_hash},
        )

    def create_with_job(
        self,
        *,
        statement: Statement,
        stage: ProcessingStage,
        payload: Mapping[str, Any],
    ) -> Statement:
        statement_query = text(
            """
            INSERT INTO statements (
                id, account_reference, original_filename, content_hash, source_path,
                page_count, status, current_stage
            ) VALUES (
                :id, :account_reference, :original_filename, :content_hash, :source_path,
                :page_count, :status, :current_stage
            )
            RETURNING *
            """
        )
        job_query = text(
            """
            INSERT INTO processing_jobs (statement_id, stage, payload)
            VALUES (:statement_id, :stage, CAST(:payload AS jsonb))
            """
        )
        with self._engine.begin() as connection:
            row = (
                connection.execute(
                    statement_query,
                    {
                        "id": statement.id,
                        "account_reference": statement.account_reference,
                        "original_filename": statement.original_filename,
                        "content_hash": statement.content_hash,
                        "source_path": str(statement.source_path),
                        "page_count": statement.page_count,
                        "status": statement.status,
                        "current_stage": statement.current_stage.value,
                    },
                )
                .mappings()
                .one()
            )
            connection.execute(
                job_query,
                {
                    "statement_id": statement.id,
                    "stage": stage.value,
                    "payload": json.dumps(dict(payload)),
                },
            )
        return _statement(row)

    def get(self, statement_id: UUID) -> Statement | None:
        return self._one_or_none(
            "SELECT * FROM statements WHERE id = :statement_id",
            {"statement_id": statement_id},
        )

    def list(self, *, limit: int = 100) -> tuple[Statement, ...]:
        if limit < 1 or limit > 100:
            raise ValueError("limit must be between 1 and 100")
        with self._engine.connect() as connection:
            rows = (
                connection.execute(
                    text("SELECT * FROM statements ORDER BY created_at DESC, id LIMIT :limit"),
                    {"limit": limit},
                )
                .mappings()
                .all()
            )
        return tuple(_statement(row) for row in rows)

    def save_extracted_pages_and_enqueue(
        self,
        *,
        statement_id: UUID,
        pages: Sequence[ExtractedPage],
        predecessor_job_id: UUID,
        next_stage: ProcessingStage,
    ) -> Statement:
        return self._update_and_enqueue(
            statement_id=statement_id,
            assignments="""
                extracted_pages = CAST(:value AS jsonb),
                current_stage = 'extract_transactions'
            """,
            values={
                "value": json.dumps([{"number": page.number, "text": page.text} for page in pages])
            },
            predecessor_job_id=predecessor_job_id,
            next_stage=next_stage,
        )

    def save_extraction_and_enqueue(
        self,
        *,
        statement_id: UUID,
        result: Mapping[str, Any],
        predecessor_job_id: UUID,
        next_stage: ProcessingStage,
    ) -> Statement:
        return self._update_and_enqueue(
            statement_id=statement_id,
            assignments="extraction_result = CAST(:value AS jsonb), current_stage = 'validate'",
            values={"value": json.dumps(dict(result))},
            predecessor_job_id=predecessor_job_id,
            next_stage=next_stage,
            transaction_candidates=tuple(
                TransactionCandidate.model_validate(candidate)
                for candidate in cast(list[object], result.get("transactions", []))
            ),
        )

    def save_validation_and_enqueue(
        self,
        *,
        statement_id: UUID,
        result: Mapping[str, Any],
        findings: Sequence[Mapping[str, Any]],
        predecessor_job_id: UUID,
        next_stage: ProcessingStage,
        correction_revision: int = 0,
    ) -> Statement:
        return self._update_and_enqueue(
            statement_id=statement_id,
            assignments="""
                validation_result = CAST(:value AS jsonb),
                review_findings = CAST(:findings AS jsonb),
                current_stage = :current_stage
            """,
            values={
                "value": json.dumps(dict(result)),
                "findings": json.dumps([dict(finding) for finding in findings]),
                "current_stage": next_stage.value,
            },
            predecessor_job_id=predecessor_job_id,
            next_stage=next_stage,
            review_findings=findings,
            validation_result=result,
            correction_revision=correction_revision,
        )

    def list_transactions(self, *, filters: TransactionFilters) -> TransactionPage:
        if filters.limit < 1 or filters.limit > 50:
            raise ValueError("transaction limit must be between 1 and 50")
        if filters.offset < 0:
            raise ValueError("transaction offset must not be negative")
        order_columns = {
            "booking_date": "COALESCE(correction.booking_date, t.booking_date)",
            "signed_amount": "COALESCE(correction.signed_amount, t.signed_amount)",
            "description": "COALESCE(correction.description, t.description)",
            "source_ordinal": "t.source_ordinal",
        }
        where = ["TRUE"]
        values: dict[str, object] = {
            "limit": filters.limit,
            "offset": filters.offset,
        }
        classification_join = """
            LEFT JOIN LATERAL (
                SELECT tc.id AS classification_id, tc.reporting_category, tc.movement_kind,
                       tc.payment_channel, tc.classification_status,
                       tc.classification_confidence, tc.classification_provenance
                FROM transaction_classifications AS tc
                WHERE tc.transaction_id = t.id
                ORDER BY tc.id DESC
                LIMIT 1
            ) AS classification ON true
        """
        correction_join = """
            LEFT JOIN LATERAL (
                SELECT c.*
                FROM transaction_corrections AS c
                WHERE c.transaction_id = t.id
                ORDER BY c.revision DESC
                LIMIT 1
            ) AS correction ON true
        """
        review_join = """
            LEFT JOIN LATERAL (
                SELECT review.decision
                FROM transaction_classification_reviews AS review
                WHERE review.transaction_id = t.id
                  AND review.classification_id = classification.classification_id
                ORDER BY review.id DESC
                LIMIT 1
            ) AS classification_review ON true
        """
        if filters.statement_id is not None:
            where.append("t.statement_id = :statement_id")
            values["statement_id"] = filters.statement_id
        if filters.review_only:
            where.append(
                "(EXISTS (SELECT 1 FROM review_findings review_filter "
                "WHERE review_filter.transaction_id = t.id) "
                "OR EXISTS (SELECT 1 FROM statements review_statement "
                "WHERE review_statement.id = t.statement_id "
                "AND review_statement.status = 'needs_review'))"
            )
        if filters.booking_date_from is not None:
            where.append("COALESCE(correction.booking_date, t.booking_date) >= :booking_date_from")
            values["booking_date_from"] = filters.booking_date_from
        if filters.booking_date_to is not None:
            where.append("COALESCE(correction.booking_date, t.booking_date) <= :booking_date_to")
            values["booking_date_to"] = filters.booking_date_to
        if filters.description_query:
            description_query = (
                filters.description_query.strip()
                .replace("\\", "\\\\")
                .replace("%", "\\%")
                .replace("_", "\\_")
            )
            if description_query:
                where.append(
                    "COALESCE(correction.description, t.description) "
                    "ILIKE :description_pattern ESCAPE '\\'"
                )
                values["description_pattern"] = f"%{description_query}%"
        if filters.amount_min is not None:
            where.append("ABS(COALESCE(correction.signed_amount, t.signed_amount)) >= :amount_min")
            values["amount_min"] = filters.amount_min
        if filters.amount_max is not None:
            where.append("ABS(COALESCE(correction.signed_amount, t.signed_amount)) <= :amount_max")
            values["amount_max"] = filters.amount_max
        if filters.money_direction == "in":
            where.append("COALESCE(correction.signed_amount, t.signed_amount) > 0")
        elif filters.money_direction == "out":
            where.append("COALESCE(correction.signed_amount, t.signed_amount) < 0")
        if filters.movement_kind is not None:
            where.append(
                "CASE WHEN correction.id IS NOT NULL THEN correction.movement_kind "
                "ELSE classification.movement_kind END = :movement_kind"
            )
            values["movement_kind"] = filters.movement_kind
        if filters.classification_status is not None:
            where.append(
                "COALESCE(classification.classification_status, 'unclassified') "
                "= :classification_status"
            )
            values["classification_status"] = filters.classification_status
        if filters.payment_channel is not None:
            where.append(
                "CASE WHEN correction.id IS NOT NULL THEN correction.payment_channel "
                "ELSE classification.payment_channel END = :payment_channel"
            )
            values["payment_channel"] = filters.payment_channel
        if filters.transfer_scope is not None:
            where.append(
                "CASE WHEN correction.id IS NOT NULL THEN correction.transfer_scope "
                "ELSE t.transfer_scope END = :transfer_scope"
            )
            values["transfer_scope"] = filters.transfer_scope
        if filters.reporting_category is not None:
            where.append(
                "CASE WHEN correction.id IS NOT NULL THEN correction.reporting_category "
                "ELSE classification.reporting_category END = :reporting_category"
            )
            values["reporting_category"] = filters.reporting_category
        if filters.currency is not None:
            where.append("upper(COALESCE(correction.currency, t.currency)) = :currency")
            values["currency"] = filters.currency.upper()
        where_sql = " AND ".join(where)
        direction = "DESC" if filters.descending else "ASC"
        order_column = order_columns[filters.sort]
        with self._engine.connect() as connection:
            total = connection.execute(
                text(
                    f"SELECT count(*) FROM transactions AS t "
                    f"JOIN statements AS s ON s.id = t.statement_id "
                    f"{classification_join}{correction_join}{review_join} WHERE {where_sql}"
                ),
                values,
            ).scalar_one()
            rows = (
                connection.execute(
                    text(
                        f"""
                    SELECT
                        t.id,
                        t.statement_id,
                        s.original_filename AS statement_filename,
                        s.status AS statement_status,
                        t.source_ordinal,
                        t.booking_date AS original_booking_date,
                        t.description AS original_description,
                        t.signed_amount AS original_signed_amount,
                        t.currency AS original_currency,
                        t.counterparty AS original_counterparty,
                        t.note AS original_note,
                        t.transfer_scope AS original_transfer_scope,
                        classification.reporting_category AS original_reporting_category,
                        classification.movement_kind AS original_movement_kind,
                        classification.payment_channel AS original_payment_channel,
                        COALESCE(correction.booking_date, t.booking_date) AS booking_date,
                        COALESCE(correction.description, t.description) AS description,
                        COALESCE(correction.signed_amount, t.signed_amount) AS signed_amount,
                        COALESCE(correction.currency, t.currency) AS currency,
                        COALESCE(correction.counterparty, t.counterparty) AS counterparty,
                        COALESCE(correction.note, t.note) AS note,
                        t.confidence,
                        t.evidence_page_number,
                        t.evidence_line_start,
                        t.evidence_line_end,
                        t.evidence_quote,
                        CASE WHEN correction.id IS NOT NULL THEN correction.reporting_category
                             ELSE classification.reporting_category END AS reporting_category,
                        CASE WHEN correction.id IS NOT NULL THEN correction.movement_kind
                             ELSE classification.movement_kind END AS movement_kind,
                        CASE WHEN correction.id IS NOT NULL THEN correction.payment_channel
                             ELSE classification.payment_channel END AS payment_channel,
                        CASE WHEN correction.id IS NOT NULL THEN correction.transfer_scope
                             ELSE t.transfer_scope END AS transfer_scope,
                        classification.classification_id,
                        CASE
                            WHEN EXISTS (
                                SELECT 1
                                FROM transaction_corrections AS classification_correction
                                WHERE classification_correction.transaction_id = t.id
                                  AND classification_correction.classification_changed
                            )
                                THEN 'corrected'
                            WHEN COALESCE(
                                classification.classification_status, 'unclassified'
                            ) = 'classified'
                                OR classification_review.decision = 'accepted'
                                THEN 'accepted'
                            ELSE 'pending'
                        END AS classification_resolution,
                        COALESCE(correction.revision, 0) AS correction_revision,
                        COALESCE(classification.classification_status, 'unclassified')
                            AS classification_status,
                        classification.classification_confidence,
                        classification.classification_provenance,
                        COALESCE(
                            jsonb_agg(
                                jsonb_build_object('code', finding.code, 'message', finding.message)
                                ORDER BY finding.created_at, finding.id
                            ) FILTER (WHERE finding.id IS NOT NULL),
                            '[]'::jsonb
                        ) || COALESCE(
                            (
                                SELECT jsonb_agg(
                                    jsonb_build_object(
                                        'code', statement_finding.code,
                                        'message', statement_finding.message
                                    )
                                    ORDER BY statement_finding.created_at, statement_finding.id
                                )
                                FROM review_findings AS statement_finding
                                WHERE statement_finding.statement_id = t.statement_id
                                  AND statement_finding.transaction_id IS NULL
                            ),
                            '[]'::jsonb
                        ) AS review_findings
                    FROM transactions AS t
                    JOIN statements AS s ON s.id = t.statement_id
                    {classification_join}
                    {correction_join}
                    {review_join}
                    LEFT JOIN review_findings AS finding ON finding.transaction_id = t.id
                    WHERE {where_sql}
                    GROUP BY t.id, s.original_filename, s.status,
                             correction.id, correction.revision, correction.booking_date,
                             correction.description, correction.signed_amount, correction.currency,
                             correction.counterparty, correction.note,
                             correction.transfer_scope,
                             correction.reporting_category, correction.movement_kind,
                             correction.payment_channel,
                             classification.classification_id,
                             classification.reporting_category,
                             classification.movement_kind,
                             classification.payment_channel,
                             classification.classification_status,
                             classification.classification_confidence,
                             classification.classification_provenance,
                             classification_review.decision
                    ORDER BY {order_column} {direction}, t.id
                    LIMIT :limit OFFSET :offset
                    """
                    ),
                    values,
                )
                .mappings()
                .all()
            )
        return TransactionPage(
            items=tuple(_transaction(row) for row in rows),
            total=int(total),
            limit=filters.limit,
            offset=filters.offset,
        )

    def list_report_transactions(self) -> tuple[ReportTransaction, ...]:
        """Return effective transaction values for deterministic reporting.

        Report arithmetic belongs to the reporting module; this adapter only supplies
        the latest correction/classification state and excludes failed/archived imports.
        """
        with self._engine.connect() as connection:
            rows = (
                connection.execute(
                    text(
                        f"""
                        SELECT *
                        FROM ({_TRANSACTION_STATE_QUERY}) AS state
                        WHERE state.statement_status IN ('ready', 'needs_review')
                        ORDER BY state.booking_date DESC, state.id
                        """
                    )
                )
                .mappings()
                .all()
            )
        return tuple(_report_transaction(row) for row in rows)

    def get_transaction(self, transaction_id: UUID) -> Transaction | None:
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    text(_TRANSACTION_STATE_QUERY + " WHERE t.id = :transaction_id"),
                    {"transaction_id": transaction_id},
                )
                .mappings()
                .one_or_none()
            )
        return None if row is None else _transaction(row)

    def correct_transaction(self, transaction_id: UUID, command: CorrectionCommand) -> Transaction:
        with self._engine.begin() as connection:
            existing = connection.execute(
                text(
                    """
                    SELECT transaction_id FROM transaction_corrections
                    WHERE idempotency_key = :idempotency_key
                    """
                ),
                {"idempotency_key": command.idempotency_key},
            ).scalar_one_or_none()
            if existing is not None:
                if existing != transaction_id:
                    raise ResolutionConflictError("idempotency key belongs to another transaction")
            else:
                row = (
                    connection.execute(
                        text(
                            _TRANSACTION_STATE_QUERY
                            + " WHERE t.id = :transaction_id FOR UPDATE OF t"
                        ),
                        {"transaction_id": transaction_id},
                    )
                    .mappings()
                    .one_or_none()
                )
                if row is None:
                    raise ResolutionNotFoundError("transaction not found")
                if row["statement_status"] in {"processing", "failed", "archived"}:
                    raise ResolutionConflictError(
                        "transaction cannot be corrected in its current statement state"
                    )
                current_revision = int(row["correction_revision"] or 0)
                if current_revision != command.expected_revision:
                    raise ResolutionConflictError("transaction revision is stale")
                current = _state_values(row)
                correction = correction_from_values(
                    current_revision=current_revision,
                    current=current,
                    changes=command.changes,
                    reason=command.reason,
                    origin=command.origin,
                )
                connection.execute(
                    text(
                        """
                        INSERT INTO transaction_corrections (
                            transaction_id, revision, previous_revision,
                            booking_date, description, signed_amount, currency,
                            reporting_category, movement_kind, payment_channel,
                            counterparty, note, transfer_scope,
                            classification_changed,
                            reason, origin, idempotency_key
                        ) VALUES (
                            :transaction_id, :revision, :previous_revision,
                            :booking_date, :description, :signed_amount, :currency,
                            :reporting_category, :movement_kind, :payment_channel,
                            :counterparty, :note, :transfer_scope,
                            :classification_changed,
                            :reason, :origin, :idempotency_key
                        )
                        """
                    ),
                    {
                        "transaction_id": transaction_id,
                        "revision": correction.revision,
                        "previous_revision": correction.previous_revision,
                        **_values_parameters(correction.values),
                        "reason": correction.reason,
                        "origin": correction.origin,
                        "classification_changed": correction.classification_changed,
                        "idempotency_key": command.idempotency_key,
                    },
                )
                stage = (
                    ProcessingStage.REVALIDATE
                    if any(
                        field in command.changes
                        for field in ("booking_date", "signed_amount", "currency")
                    )
                    else ProcessingStage.REVIEW
                )
                connection.execute(
                    text(
                        """
                        UPDATE statements
                        SET status = 'processing', current_stage = :stage, updated_at = now()
                        WHERE id = (
                            SELECT statement_id FROM transactions WHERE id = :transaction_id
                        )
                        """
                    ),
                    {"stage": stage.value, "transaction_id": transaction_id},
                )
                connection.execute(
                    text(
                        """
                        INSERT INTO processing_jobs (statement_id, stage, priority, payload)
                        SELECT statement_id, :stage, 100, CAST(:payload AS jsonb)
                        FROM transactions WHERE id = :transaction_id
                        """
                    ),
                    {
                        "stage": stage.value,
                        "payload": json.dumps({"correction_revision": correction.revision}),
                        "transaction_id": transaction_id,
                    },
                )
        transaction = self.get_transaction(transaction_id)
        if transaction is None:
            raise ResolutionNotFoundError("transaction not found")
        return transaction

    def transaction_history(self, transaction_id: UUID) -> tuple[CorrectionRecord, ...]:
        with self._engine.connect() as connection:
            rows = (
                connection.execute(
                    text(
                        """
                    SELECT id, transaction_id, revision, previous_revision,
                           booking_date, description, signed_amount, currency,
                           reporting_category, movement_kind, payment_channel,
                           counterparty, note, transfer_scope,
                           classification_changed,
                           reason, origin, created_at
                    FROM transaction_corrections
                    WHERE transaction_id = :transaction_id
                    ORDER BY revision
                    """
                    ),
                    {"transaction_id": transaction_id},
                )
                .mappings()
                .all()
            )
        return tuple(_correction_record(row) for row in rows)

    def revert_transaction(self, transaction_id: UUID, command: RevertCommand) -> Transaction:
        current = self.get_transaction(transaction_id)
        if current is None:
            raise ResolutionNotFoundError("transaction not found")
        if current.correction_revision != command.expected_revision:
            raise ResolutionConflictError("transaction revision is stale")
        if command.target_revision < 0 or command.target_revision > current.correction_revision:
            raise ResolutionError("target revision is outside the transaction history")
        if command.target_revision == 0:
            if current.original_values is None:
                raise ResolutionError("original transaction values are unavailable")
            target = current.original_values
        else:
            records = self.transaction_history(transaction_id)
            target_record = next(
                (
                    record
                    for record in records
                    if record.correction.revision == command.target_revision
                ),
                None,
            )
            if target_record is None:
                raise ResolutionNotFoundError("target correction revision not found")
            target = target_record.correction.values
        changes = {
            field: getattr(target, field)
            for field in (
                "booking_date",
                "description",
                "signed_amount",
                "currency",
                "reporting_category",
                "movement_kind",
                "payment_channel",
                "transfer_scope",
            )
            if getattr(current, field) != getattr(target, field)
        }
        if not changes:
            raise ResolutionError("target revision is already effective")
        return self.correct_transaction(
            transaction_id,
            CorrectionCommand(
                expected_revision=command.expected_revision,
                changes=changes,
                reason=command.reason,
                idempotency_key=command.idempotency_key,
            ),
        )

    def accept_classification(
        self, transaction_id: UUID, acceptance: ClassificationAcceptance
    ) -> Transaction:
        with self._engine.begin() as connection:
            row = (
                connection.execute(
                    text(
                        _TRANSACTION_STATE_QUERY + " WHERE t.id = :transaction_id FOR UPDATE OF t"
                    ),
                    {"transaction_id": transaction_id},
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                raise ResolutionNotFoundError("transaction not found")
            if row["classification_id"] != acceptance.classification_id:
                raise ResolutionConflictError("classification result is stale")
            existing = (
                connection.execute(
                    text(
                        """
                    SELECT transaction_id, classification_id
                    FROM transaction_classification_reviews
                    WHERE idempotency_key = :idempotency_key
                    """
                    ),
                    {"idempotency_key": acceptance.idempotency_key},
                )
                .mappings()
                .one_or_none()
            )
            if existing is not None and (
                existing["transaction_id"] != transaction_id
                or existing["classification_id"] != acceptance.classification_id
            ):
                raise ResolutionConflictError("idempotency key belongs to another classification")
            if existing is None:
                if row["classification_status"] != "needs_review":
                    raise ResolutionConflictError(
                        "only classifications marked needs_review can be accepted"
                    )
                if row["statement_status"] != "needs_review":
                    raise ResolutionConflictError(
                        "classification cannot be accepted while the statement is processing"
                    )
                connection.execute(
                    text(
                        """
                        INSERT INTO transaction_classification_reviews (
                            transaction_id, classification_id, decision, reason, idempotency_key
                        ) VALUES (
                            :transaction_id, :classification_id, 'accepted',
                            :reason, :idempotency_key
                        )
                        """
                    ),
                    {
                        "transaction_id": transaction_id,
                        "classification_id": acceptance.classification_id,
                        "reason": acceptance.reason,
                        "idempotency_key": acceptance.idempotency_key,
                    },
                )
                connection.execute(
                    text(
                        """
                        UPDATE statements
                        SET status = 'processing', current_stage = 'review', updated_at = now()
                        WHERE id = (
                            SELECT statement_id FROM transactions WHERE id = :transaction_id
                        )
                        """
                    ),
                    {"transaction_id": transaction_id},
                )
                connection.execute(
                    text(
                        """
                        INSERT INTO processing_jobs (statement_id, stage, priority, payload)
                        SELECT statement_id, 'review', 100, '{}'::jsonb
                        FROM transactions WHERE id = :transaction_id
                        """
                    ),
                    {"transaction_id": transaction_id},
                )
        transaction = self.get_transaction(transaction_id)
        if transaction is None:
            raise ResolutionNotFoundError("transaction not found")
        return transaction

    def list_classification_inputs(self, *, statement_id: UUID) -> tuple[ClassificationInput, ...]:
        with self._engine.connect() as connection:
            rows = (
                connection.execute(
                    text(
                        """
                        SELECT source_ordinal, booking_date, description, signed_amount, currency
                        FROM transactions AS t
                        WHERE statement_id = :statement_id
                        ORDER BY source_ordinal
                        """
                    ),
                    {"statement_id": statement_id},
                )
                .mappings()
                .all()
            )
        return tuple(
            ClassificationInput(
                source_ordinal=cast(int, row["source_ordinal"]),
                booking_date=cast(date, row["booking_date"]),
                description=cast(str, row["description"]),
                signed_amount=cast(Decimal, row["signed_amount"]),
                currency=cast(str, row["currency"]),
            )
            for row in rows
        )

    def save_classifications_and_enqueue(
        self,
        *,
        statement_id: UUID,
        decisions: Sequence[ClassificationDecision],
        normalizations: Sequence[ClassificationNormalization] = (),
        provenance: Mapping[str, Any],
        predecessor_job_id: UUID,
        next_stage: ProcessingStage,
    ) -> Statement:
        insert_classification_query = text(
            """
            INSERT INTO transaction_classifications (
                transaction_id, reporting_category, movement_kind, payment_channel,
                classification_status, classification_confidence, classification_provenance
            )
            SELECT id, :reporting_category, :movement_kind, :payment_channel,
                   :classification_status, :classification_confidence,
                   CAST(:classification_provenance AS jsonb)
            FROM transactions
            WHERE statement_id = :statement_id AND source_ordinal = :source_ordinal
            """
        )
        update_statement_query = text(
            """
            UPDATE statements
            SET current_stage = 'review', updated_at = now()
            WHERE id = :statement_id
            RETURNING *
            """
        )
        enqueue_query = text(
            """
            INSERT INTO processing_jobs (statement_id, stage, payload, predecessor_job_id)
            VALUES (:statement_id, :stage, '{}'::jsonb, :predecessor_job_id)
            ON CONFLICT (predecessor_job_id) DO NOTHING
            """
        )
        with self._engine.begin() as connection:
            normalization_rules_by_ordinal: dict[int, list[str]] = {}
            for normalization in normalizations:
                normalization_rules_by_ordinal.setdefault(normalization.source_ordinal, []).append(
                    normalization.rule_id
                )
            for decision in decisions:
                decision_provenance = {
                    **provenance,
                    "confidence": decision.confidence,
                    "rationale": decision.rationale,
                    "normalization_rules": normalization_rules_by_ordinal.get(
                        decision.source_ordinal, []
                    ),
                }
                connection.execute(
                    insert_classification_query,
                    {
                        "statement_id": statement_id,
                        "source_ordinal": decision.source_ordinal,
                        "reporting_category": decision.reporting_category,
                        "movement_kind": decision.movement_kind,
                        "payment_channel": decision.payment_channel,
                        "classification_status": decision.classification_status,
                        "classification_confidence": decision.confidence,
                        "classification_provenance": json.dumps(decision_provenance),
                    },
                )
            row = (
                connection.execute(update_statement_query, {"statement_id": statement_id})
                .mappings()
                .one()
            )
            connection.execute(
                enqueue_query,
                {
                    "statement_id": statement_id,
                    "stage": next_stage.value,
                    "predecessor_job_id": predecessor_job_id,
                },
            )
        return _statement(row)

    def all_transactions_classified(self, *, statement_id: UUID) -> bool:
        return self.all_transactions_resolved(statement_id=statement_id)

    def all_transactions_resolved(self, *, statement_id: UUID) -> bool:
        with self._engine.connect() as connection:
            result = connection.execute(
                text(
                    """
                    SELECT NOT EXISTS (
                        SELECT 1
                        FROM transactions AS t
                        WHERE t.statement_id = :statement_id
                          AND NOT (
                            COALESCE(
                              (
                                  SELECT tc.classification_status
                                  FROM transaction_classifications AS tc
                                  WHERE tc.transaction_id = t.id
                                  ORDER BY tc.id DESC
                                  LIMIT 1
                              ), 'unclassified'
                            ) = 'classified'
                            OR EXISTS (
                              SELECT 1
                              FROM transaction_classification_reviews AS review
                              JOIN transaction_classifications AS tc
                                ON tc.id = review.classification_id
                              WHERE review.transaction_id = t.id
                                AND review.decision = 'accepted'
                                AND review.classification_id = (
                                    SELECT latest.id
                                    FROM transaction_classifications AS latest
                                    WHERE latest.transaction_id = t.id
                                    ORDER BY latest.id DESC
                                    LIMIT 1
                                )
                            )
                            OR EXISTS (
                              SELECT 1
                              FROM transaction_corrections AS correction
                              WHERE correction.transaction_id = t.id
                                AND correction.classification_changed
                                AND correction.movement_kind IS NOT NULL
                            )
                          )
                    )
                    """
                ),
                {"statement_id": statement_id},
            ).scalar_one()
        return bool(result)

    def list_effective_values(self, *, statement_id: UUID) -> tuple[TransactionValues, ...]:
        with self._engine.connect() as connection:
            rows = (
                connection.execute(
                    text(
                        _TRANSACTION_STATE_QUERY
                        + " WHERE t.statement_id = :statement_id ORDER BY t.source_ordinal"
                    ),
                    {"statement_id": statement_id},
                )
                .mappings()
                .all()
            )
        return tuple(_state_values(row) for row in rows)

    def current_correction_revision(self, *, statement_id: UUID) -> int:
        with self._engine.connect() as connection:
            revision = connection.execute(
                text(
                    """
                    SELECT COALESCE(MAX(correction.revision), 0)
                    FROM transactions AS t
                    LEFT JOIN transaction_corrections AS correction
                      ON correction.transaction_id = t.id
                    WHERE t.statement_id = :statement_id
                    """
                ),
                {"statement_id": statement_id},
            ).scalar_one()
        return int(revision or 0)

    def publish_status(self, *, statement_id: UUID, ready: bool) -> Statement:
        return self._update(
            statement_id=statement_id,
            assignments="status = :status, current_stage = 'publish_state'",
            values={"status": "ready" if ready else "needs_review"},
        )

    def mark_failed(self, *, statement_id: UUID, error_code: str) -> Statement:
        return self._update(
            statement_id=statement_id,
            assignments="status = 'failed', last_error_code = :error_code",
            values={"error_code": error_code},
        )

    def restart_with_job(self, *, statement_id: UUID) -> Statement:
        statement_query = text(
            """
            UPDATE statements
            SET status = 'processing', last_error_code = NULL, updated_at = now()
            WHERE id = :statement_id AND status = 'failed'
            RETURNING *
            """
        )
        job_query = text(
            """
            INSERT INTO processing_jobs (statement_id, stage, payload)
            VALUES (:statement_id, :stage, '{}'::jsonb)
            """
        )
        with self._engine.begin() as connection:
            row = (
                connection.execute(statement_query, {"statement_id": statement_id}).mappings().one()
            )
            connection.execute(
                job_query,
                {
                    "statement_id": statement_id,
                    "stage": cast(str, row["current_stage"]),
                },
            )
        return _statement(row)

    def reprocess_from_source(self, *, statement_id: UUID) -> Statement | None:
        statement_query = text(
            """
            SELECT s.*
            FROM statements AS s
            WHERE s.id = :statement_id
              AND s.status = 'failed'
              AND s.current_stage IN ('extract_text', 'extract_transactions')
              AND s.extraction_result IS NULL
              AND NOT EXISTS (
                  SELECT 1 FROM transactions AS t WHERE t.statement_id = s.id
              )
            FOR UPDATE
            """
        )
        update_query = text(
            """
            UPDATE statements
            SET status = 'processing',
                current_stage = 'extract_text',
                extracted_pages = NULL,
                validation_result = NULL,
                review_findings = '[]'::jsonb,
                last_error_code = NULL,
                updated_at = now()
            WHERE id = :statement_id
            RETURNING *
            """
        )
        job_query = text(
            """
            INSERT INTO processing_jobs (statement_id, stage, payload)
            VALUES (:statement_id, 'extract_text', '{}'::jsonb)
            """
        )
        with self._engine.begin() as connection:
            eligible = (
                connection.execute(statement_query, {"statement_id": statement_id})
                .mappings()
                .one_or_none()
            )
            if eligible is None:
                return None
            row = connection.execute(update_query, {"statement_id": statement_id}).mappings().one()
            connection.execute(job_query, {"statement_id": statement_id})
        return _statement(row)

    def _one_or_none(self, query: str, values: Mapping[str, object]) -> Statement | None:
        with self._engine.connect() as connection:
            row = connection.execute(text(query), values).mappings().one_or_none()
        return None if row is None else _statement(row)

    def _update(
        self,
        *,
        statement_id: UUID,
        assignments: str,
        values: Mapping[str, object],
    ) -> Statement:
        query = text(
            f"""
            UPDATE statements
            SET {assignments}, updated_at = now()
            WHERE id = :statement_id
            RETURNING *
            """
        )
        with self._engine.begin() as connection:
            row = (
                connection.execute(query, {**values, "statement_id": statement_id}).mappings().one()
            )
        return _statement(row)

    def _update_and_enqueue(
        self,
        *,
        statement_id: UUID,
        assignments: str,
        values: Mapping[str, object],
        predecessor_job_id: UUID,
        next_stage: ProcessingStage,
        transaction_candidates: Sequence[TransactionCandidate] | None = None,
        review_findings: Sequence[Mapping[str, Any]] | None = None,
        validation_result: Mapping[str, Any] | None = None,
        correction_revision: int = 0,
    ) -> Statement:
        update_query = text(
            f"""
            UPDATE statements
            SET {assignments}, updated_at = now()
            WHERE id = :statement_id
            RETURNING *
            """
        )
        enqueue_query = text(
            """
            INSERT INTO processing_jobs (
                statement_id, stage, payload, predecessor_job_id
            ) VALUES (
                :statement_id, :stage, '{}'::jsonb, :predecessor_job_id
            )
            ON CONFLICT (predecessor_job_id) DO NOTHING
            """
        )
        with self._engine.begin() as connection:
            if transaction_candidates is not None:
                for ordinal, candidate in enumerate(transaction_candidates, start=1):
                    source_identity = _source_identity(candidate, ordinal=ordinal)
                    existing_id = connection.execute(
                        text(
                            """
                            SELECT id FROM transactions
                            WHERE statement_id = :statement_id
                              AND source_ordinal = :source_ordinal
                              AND evidence_page_number IS NOT DISTINCT FROM
                                  :evidence_page_number
                              AND evidence_quote IS NOT DISTINCT FROM :evidence_quote
                            LIMIT 1
                            """
                        ),
                        {
                            "statement_id": statement_id,
                            "source_ordinal": ordinal,
                            "evidence_page_number": candidate.evidence_page_number,
                            "evidence_quote": candidate.evidence_quote,
                        },
                    ).scalar_one_or_none()
                    if existing_id is not None:
                        continue
                    connection.execute(
                        text(
                            """
                            INSERT INTO transactions (
                                id, statement_id, source_ordinal, booking_date, description,
                                signed_amount, currency, confidence, evidence_page_number,
                                evidence_line_start, evidence_line_end, evidence_quote,
                                source_identity, counterparty, note
                            ) VALUES (
                                :id, :statement_id, :source_ordinal, :booking_date, :description,
                                :signed_amount, :currency, :confidence, :evidence_page_number,
                                :evidence_line_start, :evidence_line_end, :evidence_quote,
                                :source_identity, NULL, NULL
                            )
                            ON CONFLICT DO NOTHING
                            """
                        ),
                        {
                            "id": _transaction_id(statement_id, source_identity),
                            "statement_id": statement_id,
                            "source_ordinal": ordinal,
                            "booking_date": candidate.booking_date,
                            "description": candidate.description,
                            "signed_amount": candidate.signed_amount,
                            "currency": candidate.currency.upper(),
                            "confidence": candidate.confidence,
                            "evidence_page_number": candidate.evidence_page_number,
                            "evidence_line_start": candidate.evidence_line_start,
                            "evidence_line_end": candidate.evidence_line_end,
                            "evidence_quote": candidate.evidence_quote,
                            "source_identity": source_identity,
                        },
                    )
            if review_findings is not None:
                connection.execute(
                    text("DELETE FROM review_findings WHERE statement_id = :statement_id"),
                    {"statement_id": statement_id},
                )
                for finding in review_findings:
                    transaction_id = None
                    transaction_index = finding.get("transaction_index")
                    if isinstance(transaction_index, int):
                        transaction_id = connection.execute(
                            text(
                                """
                                SELECT id FROM transactions
                                WHERE statement_id = :statement_id
                                  AND source_ordinal = :source_ordinal
                                """
                            ),
                            {
                                "statement_id": statement_id,
                                "source_ordinal": transaction_index + 1,
                            },
                        ).scalar_one_or_none()
                    connection.execute(
                        text(
                            """
                            INSERT INTO review_findings (
                                statement_id, transaction_id, code, message
                            ) VALUES (
                                :statement_id, :transaction_id, :code, :message
                            )
                            """
                        ),
                        {
                            "statement_id": statement_id,
                            "transaction_id": transaction_id,
                            "code": cast(str, finding["code"]),
                            "message": cast(str, finding["message"]),
                        },
                    )
            if validation_result is not None:
                connection.execute(
                    text(
                        """
                        INSERT INTO statement_validation_runs (
                            statement_id, correction_revision, is_valid, result, findings
                        ) VALUES (
                            :statement_id, :correction_revision, :is_valid,
                            CAST(:result AS jsonb), CAST(:findings AS jsonb)
                        )
                        """
                    ),
                    {
                        "statement_id": statement_id,
                        "correction_revision": correction_revision,
                        "is_valid": bool(validation_result.get("is_valid", False)),
                        "result": json.dumps(dict(validation_result)),
                        "findings": json.dumps(
                            [dict(finding) for finding in review_findings or ()]
                        ),
                    },
                )
            row = (
                connection.execute(
                    update_query,
                    {**values, "statement_id": statement_id},
                )
                .mappings()
                .one()
            )
            connection.execute(
                enqueue_query,
                {
                    "statement_id": statement_id,
                    "stage": next_stage.value,
                    "predecessor_job_id": predecessor_job_id,
                },
            )
        return _statement(row)


def _statement(row: RowMapping) -> Statement:
    extracted_pages = cast(list[dict[str, object]] | None, row["extracted_pages"])
    review_findings = cast(list[dict[str, Any]] | None, row["review_findings"])
    return Statement(
        id=cast(UUID, row["id"]),
        account_reference=cast(str, row["account_reference"]),
        original_filename=cast(str, row["original_filename"]),
        content_hash=cast(str, row["content_hash"]),
        source_path=Path(cast(str, row["source_path"])),
        page_count=cast(int, row["page_count"]),
        status=cast(StatementStatus, row["status"]),
        current_stage=ProcessingStage(cast(str, row["current_stage"])),
        extracted_pages=tuple(
            ExtractedPage(number=cast(int, page["number"]), text=cast(str, page["text"]))
            for page in extracted_pages or []
        ),
        extraction_result=cast(dict[str, Any] | None, row["extraction_result"]),
        validation_result=cast(dict[str, Any] | None, row["validation_result"]),
        review_findings=tuple(review_findings or []),
        last_error_code=cast(str | None, row["last_error_code"]),
        created_at=row["created_at"],
    )


_TRANSACTION_STATE_QUERY = """
    SELECT
        t.id, t.statement_id, s.original_filename AS statement_filename,
        s.status AS statement_status, t.source_ordinal,
        t.booking_date AS original_booking_date,
        t.description AS original_description,
        t.signed_amount AS original_signed_amount,
        t.currency AS original_currency,
        t.counterparty AS original_counterparty,
        t.note AS original_note,
        t.transfer_scope AS original_transfer_scope,
        t.confidence, t.evidence_page_number, t.evidence_line_start,
        t.evidence_line_end, t.evidence_quote, t.created_at,
        classification.id AS classification_id,
        classification.reporting_category AS original_reporting_category,
        classification.movement_kind AS original_movement_kind,
        classification.payment_channel AS original_payment_channel,
        classification.classification_confidence,
        classification.classification_provenance,
        classification_review.decision AS classification_review_decision,
        correction.id AS correction_id,
        correction.revision AS correction_revision,
        correction.booking_date AS correction_booking_date,
        correction.description AS correction_description,
        correction.signed_amount AS correction_signed_amount,
        correction.currency AS correction_currency,
        correction.counterparty AS correction_counterparty,
        correction.note AS correction_note,
        correction.transfer_scope AS correction_transfer_scope,
        correction.reporting_category AS correction_reporting_category,
        correction.movement_kind AS correction_movement_kind,
        correction.payment_channel AS correction_payment_channel,
        correction.classification_changed AS correction_classification_changed,
        CASE WHEN correction.id IS NOT NULL THEN correction.booking_date
             ELSE t.booking_date END AS booking_date,
        CASE WHEN correction.id IS NOT NULL THEN correction.description
             ELSE t.description END AS description,
        CASE WHEN correction.id IS NOT NULL THEN correction.signed_amount
             ELSE t.signed_amount END AS signed_amount,
        CASE WHEN correction.id IS NOT NULL THEN correction.currency
             ELSE t.currency END AS currency,
        CASE WHEN correction.id IS NOT NULL THEN correction.counterparty
             ELSE t.counterparty END AS counterparty,
        CASE WHEN correction.id IS NOT NULL THEN correction.note
             ELSE t.note END AS note,
        CASE WHEN correction.id IS NOT NULL THEN correction.reporting_category
             ELSE classification.reporting_category END AS reporting_category,
        CASE WHEN correction.id IS NOT NULL THEN correction.movement_kind
             ELSE classification.movement_kind END AS movement_kind,
        CASE WHEN correction.id IS NOT NULL THEN correction.payment_channel
             ELSE classification.payment_channel END AS payment_channel,
        CASE WHEN correction.id IS NOT NULL THEN correction.transfer_scope
             ELSE t.transfer_scope END AS transfer_scope,
        COALESCE(classification.classification_status, 'unclassified')
            AS classification_status,
        CASE
            WHEN EXISTS (
                SELECT 1
                FROM transaction_corrections AS classification_correction
                WHERE classification_correction.transaction_id = t.id
                  AND classification_correction.classification_changed
                  AND classification_correction.movement_kind IS NOT NULL
            )
                THEN 'corrected'
            WHEN COALESCE(classification.classification_status, 'unclassified') = 'classified'
                OR classification_review.decision = 'accepted'
                THEN 'accepted'
            ELSE 'pending'
        END AS classification_resolution,
        COALESCE(correction.revision, 0) AS correction_revision,
        COALESCE(
            (
                SELECT jsonb_agg(
                    jsonb_build_object('code', finding.code, 'message', finding.message)
                    ORDER BY finding.created_at, finding.id
                )
                FROM review_findings AS finding
                WHERE finding.transaction_id = t.id
            ), '[]'::jsonb
        ) || COALESCE(
            (
                SELECT jsonb_agg(
                    jsonb_build_object(
                        'code', statement_finding.code,
                        'message', statement_finding.message
                    )
                    ORDER BY statement_finding.created_at, statement_finding.id
                )
                FROM review_findings AS statement_finding
                WHERE statement_finding.statement_id = t.statement_id
                  AND statement_finding.transaction_id IS NULL
            ), '[]'::jsonb
        ) AS review_findings
    FROM transactions AS t
    JOIN statements AS s ON s.id = t.statement_id
    LEFT JOIN LATERAL (
        SELECT tc.id, tc.reporting_category, tc.movement_kind,
               tc.payment_channel, tc.classification_status,
               tc.classification_confidence, tc.classification_provenance
        FROM transaction_classifications AS tc
        WHERE tc.transaction_id = t.id
        ORDER BY tc.id DESC
        LIMIT 1
    ) AS classification ON true
    LEFT JOIN LATERAL (
        SELECT review.decision
        FROM transaction_classification_reviews AS review
        WHERE review.transaction_id = t.id
          AND review.classification_id = classification.id
        ORDER BY review.id DESC
        LIMIT 1
    ) AS classification_review ON true
    LEFT JOIN LATERAL (
        SELECT c.*
        FROM transaction_corrections AS c
        WHERE c.transaction_id = t.id
        ORDER BY c.revision DESC
        LIMIT 1
    ) AS correction ON true
"""


def _state_values(row: RowMapping) -> TransactionValues:
    corrected = row["correction_id"] is not None
    return TransactionValues(
        booking_date=cast(
            date,
            row["correction_booking_date"] if corrected else row["original_booking_date"],
        ),
        description=cast(
            str,
            row["correction_description"] if corrected else row["original_description"],
        ),
        signed_amount=cast(
            Decimal,
            row["correction_signed_amount"] if corrected else row["original_signed_amount"],
        ),
        currency=cast(
            str,
            row["correction_currency"] if corrected else row["original_currency"],
        ),
        counterparty=cast(
            str | None,
            row["correction_counterparty"] if corrected else row["original_counterparty"],
        ),
        note=cast(str | None, row["correction_note"] if corrected else row["original_note"]),
        reporting_category=cast(
            ReportingCategory | None,
            row["correction_reporting_category"]
            if corrected
            else row["original_reporting_category"],
        ),
        movement_kind=cast(
            MovementKind | None,
            row["correction_movement_kind"] if corrected else row["original_movement_kind"],
        ),
        payment_channel=cast(
            PaymentChannel | None,
            row["correction_payment_channel"] if corrected else row["original_payment_channel"],
        ),
        transfer_scope=cast(
            TransferScope | None,
            row["correction_transfer_scope"] if corrected else row["original_transfer_scope"],
        ),
    )


def _values_parameters(values: TransactionValues) -> dict[str, object]:
    return {
        "booking_date": values.booking_date,
        "description": values.description,
        "signed_amount": values.signed_amount,
        "currency": values.currency,
        "counterparty": values.counterparty,
        "note": values.note,
        "reporting_category": values.reporting_category,
        "movement_kind": values.movement_kind,
        "payment_channel": values.payment_channel,
        "transfer_scope": values.transfer_scope,
    }


def _correction_record(row: RowMapping) -> CorrectionRecord:
    values = TransactionValues(
        booking_date=cast(date, row["booking_date"]),
        description=cast(str, row["description"]),
        signed_amount=cast(Decimal, row["signed_amount"]),
        currency=cast(str, row["currency"]),
        reporting_category=cast(ReportingCategory | None, row["reporting_category"]),
        movement_kind=cast(MovementKind | None, row["movement_kind"]),
        payment_channel=cast(PaymentChannel | None, row["payment_channel"]),
        counterparty=cast(str | None, row["counterparty"]),
        note=cast(str | None, row["note"]),
        transfer_scope=cast(TransferScope | None, row["transfer_scope"]),
    )
    return CorrectionRecord(
        id=cast(UUID, row["id"]),
        transaction_id=cast(UUID, row["transaction_id"]),
        correction=TransactionCorrection(
            revision=int(row["revision"]),
            previous_revision=int(row["previous_revision"]),
            values=values,
            reason=cast(str, row["reason"]),
            origin=cast(str, row["origin"]),
            classification_changed=bool(row["classification_changed"]),
        ),
        reason=cast(str, row["reason"]),
        origin=cast(str, row["origin"]),
        created_at=row["created_at"],
    )


def _source_identity(candidate: TransactionCandidate, *, ordinal: int) -> str:
    if candidate.evidence_line_start is not None and candidate.evidence_line_end is not None:
        return (
            f"page:{candidate.evidence_page_number}:"
            f"lines:{candidate.evidence_line_start}-{candidate.evidence_line_end}"
        )
    return f"ordinal:{ordinal}"


def _transaction_id(statement_id: UUID, source_identity: str) -> UUID:
    return uuid5(
        NAMESPACE_URL,
        f"bank-statement-assistant:transaction:{statement_id}:{source_identity}",
    )


def _transaction(row: RowMapping) -> Transaction:
    findings = cast(list[dict[str, str]] | None, row["review_findings"])
    return Transaction(
        id=cast(UUID, row["id"]),
        statement_id=cast(UUID, row["statement_id"]),
        statement_filename=cast(str, row["statement_filename"]),
        statement_status=cast(StatementStatus, row["statement_status"]),
        source_ordinal=cast(int, row["source_ordinal"]),
        booking_date=cast(date, row["booking_date"]),
        description=cast(str, row["description"]),
        signed_amount=cast(Decimal, row["signed_amount"]),
        currency=cast(str, row["currency"]),
        confidence=float(cast(Decimal, row["confidence"])),
        evidence_page_number=cast(int | None, row["evidence_page_number"]),
        evidence_line_start=cast(int | None, row["evidence_line_start"]),
        evidence_line_end=cast(int | None, row["evidence_line_end"]),
        evidence_quote=cast(str | None, row["evidence_quote"]),
        reporting_category=cast(ReportingCategory | None, row["reporting_category"]),
        movement_kind=cast(MovementKind | None, row["movement_kind"]),
        payment_channel=cast(PaymentChannel | None, row["payment_channel"]),
        counterparty=cast(str | None, row.get("counterparty")),
        note=cast(str | None, row.get("note")),
        transfer_scope=cast(TransferScope | None, row.get("transfer_scope")),
        classification_status=cast(ClassificationStatus, row["classification_status"]),
        classification_confidence=(
            None
            if row["classification_confidence"] is None
            else float(cast(Decimal, row["classification_confidence"]))
        ),
        classification_provenance=cast(dict[str, object] | None, row["classification_provenance"]),
        review_findings=tuple(findings or []),
        created_at=cast(datetime, row["created_at"]) if "created_at" in row else None,
        classification_id=(
            None
            if row.get("classification_id") is None
            else int(cast(int, row["classification_id"]))
        ),
        classification_resolution=cast(
            ClassificationResolution,
            row.get("classification_resolution", "pending"),
        ),
        correction_revision=int(row.get("correction_revision", 0) or 0),
        original_values=(
            TransactionValues(
                booking_date=cast(date, row.get("original_booking_date", row["booking_date"])),
                description=cast(str, row.get("original_description", row["description"])),
                signed_amount=cast(
                    Decimal, row.get("original_signed_amount", row["signed_amount"])
                ),
                currency=cast(str, row.get("original_currency", row["currency"])),
                counterparty=cast(str | None, row.get("original_counterparty")),
                note=cast(str | None, row.get("original_note")),
                reporting_category=cast(
                    ReportingCategory | None,
                    row.get("original_reporting_category"),
                ),
                movement_kind=cast(MovementKind | None, row.get("original_movement_kind")),
                payment_channel=cast(PaymentChannel | None, row.get("original_payment_channel")),
                transfer_scope=cast(TransferScope | None, row.get("original_transfer_scope")),
            )
        ),
    )


def _report_transaction(row: RowMapping) -> ReportTransaction:
    transfer_scope = cast(TransferScope | None, row["transfer_scope"])
    movement_kind = cast(MovementKind | None, row["movement_kind"])
    if movement_kind == "Transfer" and transfer_scope is None:
        transfer_scope = "unknown"
    return ReportTransaction(
        id=cast(UUID, row["id"]),
        statement_id=cast(UUID, row["statement_id"]),
        booking_date=cast(date, row["booking_date"]),
        description=cast(str, row["description"]),
        signed_amount=cast(Decimal, row["signed_amount"]),
        currency=cast(str, row["currency"]),
        reporting_category=cast(ReportingCategory | None, row["reporting_category"]),
        movement_kind=movement_kind,
        payment_channel=cast(PaymentChannel | None, row["payment_channel"]),
        counterparty=cast(str | None, row["counterparty"]),
        transfer_scope=transfer_scope,
        is_provisional=(
            row["statement_status"] != "ready"
            or row["classification_resolution"] == "pending"
        ),
        is_unresolved=(
            movement_kind is None
            or row["classification_resolution"] == "pending"
            or (movement_kind == "Transfer" and transfer_scope == "unknown")
        ),
    )
