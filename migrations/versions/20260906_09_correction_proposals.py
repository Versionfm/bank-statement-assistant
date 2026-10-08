"""Add immutable assistant correction proposals."""

from alembic import op

revision = "20260906_09"
down_revision = "20260906_08"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE transaction_correction_proposals (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            transaction_id uuid NOT NULL REFERENCES transactions(id) ON DELETE CASCADE,
            expected_revision integer NOT NULL,
            before_values jsonb NOT NULL,
            proposed_changes jsonb NOT NULL,
            reason text NOT NULL,
            evidence jsonb NOT NULL DEFAULT '[]'::jsonb,
            model text NOT NULL,
            prompt_version text NOT NULL,
            status text NOT NULL DEFAULT 'pending',
            idempotency_key text NOT NULL UNIQUE,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT transaction_correction_proposals_revision_check
                CHECK (expected_revision >= 0),
            CONSTRAINT transaction_correction_proposals_status_check
                CHECK (status IN ('pending', 'accepted', 'rejected'))
        );
        CREATE INDEX transaction_correction_proposals_transaction_idx
        ON transaction_correction_proposals (transaction_id, created_at DESC);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX transaction_correction_proposals_transaction_idx;
        DROP TABLE transaction_correction_proposals;
        """
    )
