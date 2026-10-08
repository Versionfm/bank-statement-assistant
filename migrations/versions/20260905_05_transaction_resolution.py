"""Add append-only transaction corrections and classification review decisions.

Revision ID: 20260905_05
Revises: 20260904_04
Create Date: 2026-09-05
"""

from alembic import op

revision = "20260905_05"
down_revision = "20260904_04"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE transaction_corrections (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            transaction_id uuid NOT NULL REFERENCES transactions(id) ON DELETE CASCADE,
            revision integer NOT NULL,
            previous_revision integer NOT NULL,
            booking_date date NOT NULL,
            description text NOT NULL,
            signed_amount numeric(20, 4) NOT NULL,
            currency char(3) NOT NULL,
            reporting_category text,
            movement_kind text,
            payment_channel text,
            classification_changed boolean NOT NULL DEFAULT false,
            reason text NOT NULL,
            origin text NOT NULL DEFAULT 'user',
            idempotency_key text NOT NULL UNIQUE,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT transaction_corrections_revision_check CHECK (
                revision > 0 AND previous_revision = revision - 1
            ),
            CONSTRAINT transaction_corrections_currency_check CHECK (
                currency = upper(currency)
            ),
            CONSTRAINT transaction_corrections_origin_check CHECK (
                origin IN ('user', 'assistant_proposal')
            ),
            CONSTRAINT transaction_corrections_category_check CHECK (
                reporting_category IS NULL OR reporting_category IN (
                    'Groceries', 'Restaurants & Cafes', 'Housing', 'Utilities',
                    'Transport', 'Health', 'Insurance', 'Subscriptions', 'Shopping',
                    'Leisure', 'Travel', 'Education', 'Gifts & Donations', 'Taxes',
                    'Other Expense', 'Salary', 'Interest', 'Other Income', 'Bank Fees'
                )
            ),
            CONSTRAINT transaction_corrections_movement_check CHECK (
                movement_kind IS NULL OR movement_kind IN (
                    'Expense', 'Income', 'Transfer', 'Refund', 'Fee'
                )
            ),
            CONSTRAINT transaction_corrections_channel_check CHECK (
                payment_channel IS NULL OR payment_channel IN (
                    'MB WAY', 'Card', 'Bank Transfer', 'Direct Debit',
                    'Cash Withdrawal', 'Other'
                )
            ),
            CONSTRAINT transaction_corrections_classification_check CHECK (
                (movement_kind IS NULL AND reporting_category IS NULL AND payment_channel IS NULL)
                OR (
                    movement_kind = 'Transfer'
                    AND reporting_category IS NULL
                    AND payment_channel IS NOT NULL
                )
                OR (
                    movement_kind IS NOT NULL
                    AND movement_kind <> 'Transfer'
                    AND reporting_category IS NOT NULL
                    AND payment_channel IS NOT NULL
                )
            ),
            CONSTRAINT transaction_corrections_transaction_revision_unique
                UNIQUE (transaction_id, revision)
        );
        CREATE INDEX transaction_corrections_latest_idx
        ON transaction_corrections (transaction_id, revision DESC);

        CREATE TABLE transaction_classification_reviews (
            id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            transaction_id uuid NOT NULL REFERENCES transactions(id) ON DELETE CASCADE,
            classification_id bigint NOT NULL REFERENCES transaction_classifications(id)
                ON DELETE CASCADE,
            decision text NOT NULL,
            reason text,
            idempotency_key text NOT NULL UNIQUE,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT transaction_classification_reviews_decision_check CHECK (
                decision IN ('accepted', 'rejected')
            )
        );
        CREATE INDEX transaction_classification_reviews_latest_idx
        ON transaction_classification_reviews (transaction_id, id DESC);

        CREATE TABLE statement_validation_runs (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            statement_id uuid NOT NULL REFERENCES statements(id) ON DELETE CASCADE,
            correction_revision integer NOT NULL DEFAULT 0,
            is_valid boolean NOT NULL,
            result jsonb NOT NULL,
            findings jsonb NOT NULL DEFAULT '[]'::jsonb,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT statement_validation_runs_revision_check CHECK (
                correction_revision >= 0
            )
        );
        CREATE INDEX statement_validation_runs_latest_idx
        ON statement_validation_runs (statement_id, id DESC);

        ALTER TABLE processing_jobs DROP CONSTRAINT processing_jobs_stage_check;
        ALTER TABLE processing_jobs ADD CONSTRAINT processing_jobs_stage_check CHECK (
            stage IN (
                'accept', 'extract_text', 'extract_transactions', 'validate',
                'revalidate', 'classify', 'review', 'publish_state'
            )
        );
        ALTER TABLE statements DROP CONSTRAINT statements_stage_check;
        ALTER TABLE statements ADD CONSTRAINT statements_stage_check CHECK (
            current_stage IN (
                'extract_text', 'extract_transactions', 'validate', 'revalidate',
                'classify', 'review', 'publish_state'
            )
        );
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE statements DROP CONSTRAINT statements_stage_check;
        ALTER TABLE statements ADD CONSTRAINT statements_stage_check CHECK (
            current_stage IN (
                'extract_text', 'extract_transactions', 'validate',
                'classify', 'review', 'publish_state'
            )
        );
        ALTER TABLE processing_jobs DROP CONSTRAINT processing_jobs_stage_check;
        ALTER TABLE processing_jobs ADD CONSTRAINT processing_jobs_stage_check CHECK (
            stage IN (
                'accept', 'extract_text', 'extract_transactions', 'validate',
                'classify', 'review', 'publish_state'
            )
        );
        DROP INDEX statement_validation_runs_latest_idx;
        DROP TABLE statement_validation_runs;
        DROP INDEX transaction_classification_reviews_latest_idx;
        DROP TABLE transaction_classification_reviews;
        DROP INDEX transaction_corrections_latest_idx;
        DROP TABLE transaction_corrections;
        """
    )
