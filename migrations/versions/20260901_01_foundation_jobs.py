"""Create durable processing jobs.

Revision ID: 20260901_01
Revises:
Create Date: 2026-09-01
"""

from alembic import op

revision = "20260901_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE processing_jobs (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            statement_id uuid NOT NULL,
            stage text NOT NULL,
            payload jsonb NOT NULL DEFAULT '{}'::jsonb,
            status text NOT NULL DEFAULT 'queued',
            priority integer NOT NULL DEFAULT 0,
            attempts integer NOT NULL DEFAULT 0,
            available_at timestamptz NOT NULL DEFAULT now(),
            claimed_at timestamptz,
            claimed_by text,
            lease_expires_at timestamptz,
            last_error_code text,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT processing_jobs_status_check
                CHECK (status IN ('queued', 'running', 'succeeded', 'failed')),
            CONSTRAINT processing_jobs_attempts_check CHECK (attempts >= 0),
            CONSTRAINT processing_jobs_claim_check CHECK (
                (
                    status = 'running'
                    AND claimed_at IS NOT NULL
                    AND claimed_by IS NOT NULL
                    AND lease_expires_at IS NOT NULL
                ) OR (
                    status <> 'running' AND lease_expires_at IS NULL
                )
            ),
            CONSTRAINT processing_jobs_stage_check CHECK (
                stage IN (
                    'accept', 'extract_text', 'extract_transactions', 'validate',
                    'classify', 'review', 'publish_state'
                )
            )
        )
        """
    )
    op.execute(
        """
        CREATE INDEX processing_jobs_claimable_idx
        ON processing_jobs (priority DESC, created_at, id)
        WHERE status = 'queued'
        """
    )
    op.execute(
        """
        CREATE INDEX processing_jobs_expired_lease_idx
        ON processing_jobs (lease_expires_at, attempts)
        WHERE status = 'running'
        """
    )


def downgrade() -> None:
    op.drop_table("processing_jobs")
