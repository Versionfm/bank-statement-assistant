"""Persist extracted Transactions and their Review Findings.

Revision ID: 20260903_03
Revises: 20260902_02
Create Date: 2026-09-03
"""

from alembic import op

revision = "20260903_03"
down_revision = "20260902_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE transactions (
            id uuid PRIMARY KEY,
            statement_id uuid NOT NULL REFERENCES statements(id) ON DELETE CASCADE,
            source_ordinal integer NOT NULL,
            booking_date date NOT NULL,
            description text NOT NULL,
            signed_amount numeric(20, 4) NOT NULL,
            currency char(3) NOT NULL,
            confidence numeric(5, 4) NOT NULL,
            evidence_page_number integer,
            evidence_line_start integer,
            evidence_line_end integer,
            evidence_quote text,
            source_identity text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT transactions_source_ordinal_check CHECK (source_ordinal > 0),
            CONSTRAINT transactions_currency_check CHECK (currency = upper(currency)),
            CONSTRAINT transactions_confidence_check CHECK (confidence >= 0 AND confidence <= 1),
            CONSTRAINT transactions_evidence_page_check CHECK (
                evidence_page_number IS NULL OR evidence_page_number > 0
            ),
            CONSTRAINT transactions_evidence_coordinates_check CHECK (
                evidence_page_number IS NOT NULL
                OR (evidence_line_start IS NULL AND evidence_line_end IS NULL)
            ),
            CONSTRAINT transactions_evidence_line_check CHECK (
                (evidence_line_start IS NULL AND evidence_line_end IS NULL)
                OR (
                    evidence_line_start IS NOT NULL
                    AND evidence_line_end IS NOT NULL
                    AND evidence_line_start > 0
                    AND evidence_line_end >= evidence_line_start
                )
            ),
            CONSTRAINT transactions_source_identity_unique UNIQUE (statement_id, source_identity),
            CONSTRAINT transactions_statement_ordinal_unique UNIQUE (statement_id, source_ordinal)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE review_findings (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            statement_id uuid NOT NULL REFERENCES statements(id) ON DELETE CASCADE,
            transaction_id uuid REFERENCES transactions(id) ON DELETE CASCADE,
            code text NOT NULL,
            message text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        INSERT INTO transactions (
            id, statement_id, source_ordinal, booking_date, description,
            signed_amount, currency, confidence, evidence_page_number,
            evidence_line_start, evidence_line_end, evidence_quote, source_identity
        )
        SELECT
            md5(s.id::text || ':legacy:' || candidate.ordinality::text)::uuid,
            s.id,
            candidate.ordinality::integer,
            (candidate.value->>'booking_date')::date,
            candidate.value->>'description',
            (candidate.value->>'signed_amount')::numeric,
            upper(candidate.value->>'currency'),
            (candidate.value->>'confidence')::numeric,
            NULLIF(candidate.value->>'evidence_page_number', '')::integer,
            NULLIF(candidate.value->>'evidence_line_start', '')::integer,
            NULLIF(candidate.value->>'evidence_line_end', '')::integer,
            candidate.value->>'evidence_quote',
            'ordinal:' || candidate.ordinality::text
        FROM statements AS s
        CROSS JOIN LATERAL jsonb_array_elements(
            COALESCE(s.extraction_result->'transactions', '[]'::jsonb)
        ) WITH ORDINALITY AS candidate(value, ordinality)
        WHERE s.extraction_result IS NOT NULL
        """
    )
    op.execute(
        """
        INSERT INTO review_findings (statement_id, transaction_id, code, message)
        SELECT
            s.id,
            transaction_row.id,
            finding.value->>'code',
            finding.value->>'message'
        FROM statements AS s
        CROSS JOIN LATERAL jsonb_array_elements(
            COALESCE(s.review_findings, '[]'::jsonb)
        ) AS finding(value)
        LEFT JOIN transactions AS transaction_row
            ON transaction_row.statement_id = s.id
            AND transaction_row.source_ordinal =
                CASE
                    WHEN finding.value->>'transaction_index' ~ '^[0-9]+$'
                    THEN (finding.value->>'transaction_index')::integer + 1
                    ELSE NULL
                END
        """
    )
    op.execute(
        """
        CREATE INDEX transactions_booking_date_idx
        ON transactions (booking_date DESC, id)
        """
    )
    op.execute(
        """
        CREATE INDEX transactions_statement_idx
        ON transactions (statement_id, source_ordinal)
        """
    )
    op.execute(
        """
        CREATE INDEX review_findings_transaction_idx
        ON review_findings (transaction_id, created_at)
        """
    )


def downgrade() -> None:
    op.drop_index("review_findings_transaction_idx", table_name="review_findings")
    op.drop_index("transactions_statement_idx", table_name="transactions")
    op.drop_index("transactions_booking_date_idx", table_name="transactions")
    op.drop_table("review_findings")
    op.drop_table("transactions")
