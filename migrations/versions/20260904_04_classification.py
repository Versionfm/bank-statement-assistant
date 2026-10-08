"""Persist transaction Classification results.

Revision ID: 20260904_04
Revises: 20260903_03
Create Date: 2026-09-04
"""

from alembic import op

revision = "20260904_04"
down_revision = "20260903_03"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE transaction_classifications (
            id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            transaction_id uuid NOT NULL REFERENCES transactions(id) ON DELETE CASCADE,
            reporting_category text,
            movement_kind text NOT NULL,
            payment_channel text NOT NULL,
            classification_status text NOT NULL,
            classification_confidence numeric(5, 4) NOT NULL,
            classification_provenance jsonb NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT transaction_classifications_reporting_category_check CHECK (
                reporting_category IS NULL OR reporting_category IN (
                    'Groceries', 'Restaurants & Cafes', 'Housing', 'Utilities',
                    'Transport', 'Health', 'Insurance', 'Subscriptions', 'Shopping',
                    'Leisure', 'Travel', 'Education', 'Gifts & Donations', 'Taxes',
                    'Other Expense', 'Salary', 'Interest', 'Other Income', 'Bank Fees'
                )
            ),
            CONSTRAINT transaction_classifications_movement_kind_check CHECK (
                movement_kind IN (
                    'Expense', 'Income', 'Transfer', 'Refund', 'Fee'
                )
            ),
            CONSTRAINT transaction_classifications_payment_channel_check CHECK (
                payment_channel IN (
                    'MB WAY', 'Card', 'Bank Transfer', 'Direct Debit', 'Cash Withdrawal', 'Other'
                )
            ),
            CONSTRAINT transaction_classifications_status_check CHECK (
                classification_status IN ('unclassified', 'classified', 'needs_review')
            ),
            CONSTRAINT transaction_classifications_confidence_check CHECK (
                classification_confidence >= 0 AND classification_confidence <= 1
            ),
            CONSTRAINT transaction_classifications_complete_check CHECK (
                classification_status <> 'unclassified'
                AND (
                    (movement_kind = 'Transfer' AND reporting_category IS NULL)
                    OR (movement_kind <> 'Transfer' AND reporting_category IS NOT NULL)
                )
            )
        );
        CREATE INDEX transaction_classifications_latest_idx
        ON transaction_classifications (transaction_id, id DESC);
        """
    )


def downgrade() -> None:
    op.drop_index(
        "transaction_classifications_latest_idx",
        table_name="transaction_classifications",
    )
    op.drop_table("transaction_classifications")
