"""Persist bounded external merchant evidence snapshots for replayable classification."""

from alembic import op

revision = "20260906_08"
down_revision = "20260905_07"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE merchant_evidence_cache (
            normalized_key text PRIMARY KEY,
            query text NOT NULL,
            provider text NOT NULL,
            status text NOT NULL,
            evidence jsonb NOT NULL,
            response_hash text,
            fetched_at timestamptz,
            expires_at timestamptz NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT merchant_evidence_cache_status_check CHECK (
                status IN ('complete', 'not_found', 'unavailable', 'ambiguous', 'disabled')
            )
        );
        CREATE INDEX merchant_evidence_cache_expiry_idx
        ON merchant_evidence_cache (expires_at);
        """
    )


def downgrade() -> None:
    op.drop_index("merchant_evidence_cache_expiry_idx", table_name="merchant_evidence_cache")
    op.drop_table("merchant_evidence_cache")
