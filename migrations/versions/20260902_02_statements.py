"""Create durable statement state.

Revision ID: 20260902_02
Revises: 20260901_01
Create Date: 2026-09-02
"""

from alembic import op

revision = "20260902_02"
down_revision = "20260901_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE statements (
            id uuid PRIMARY KEY,
            account_reference text NOT NULL,
            original_filename text NOT NULL,
            content_hash text NOT NULL UNIQUE,
            source_path text NOT NULL UNIQUE,
            page_count integer NOT NULL,
            status text NOT NULL DEFAULT 'processing',
            current_stage text NOT NULL DEFAULT 'extract_text',
            extracted_pages jsonb,
            extraction_result jsonb,
            validation_result jsonb,
            review_findings jsonb,
            last_error_code text,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            archived_at timestamptz,
            CONSTRAINT statements_page_count_check CHECK (page_count > 0),
            CONSTRAINT statements_status_check CHECK (
                status IN ('processing', 'needs_review', 'ready', 'failed', 'archived')
            ),
            CONSTRAINT statements_stage_check CHECK (
                current_stage IN (
                    'extract_text', 'extract_transactions', 'validate',
                    'classify', 'review', 'publish_state'
                )
            )
        )
        """
    )
    op.execute(
        """
        ALTER TABLE processing_jobs
        ADD CONSTRAINT processing_jobs_statement_fk
        FOREIGN KEY (statement_id) REFERENCES statements(id)
        ON DELETE CASCADE NOT VALID
        """
    )
    op.execute("ALTER TABLE processing_jobs VALIDATE CONSTRAINT processing_jobs_statement_fk")
    op.execute(
        """
        ALTER TABLE processing_jobs
        ADD COLUMN predecessor_job_id uuid,
        ADD CONSTRAINT processing_jobs_predecessor_fk
            FOREIGN KEY (predecessor_job_id) REFERENCES processing_jobs(id)
            ON DELETE CASCADE,
        ADD CONSTRAINT processing_jobs_predecessor_unique UNIQUE (predecessor_job_id)
        """
    )
    op.execute(
        """
        CREATE INDEX statements_created_at_idx
        ON statements (created_at DESC, id)
        """
    )
    op.execute(
        """
        CREATE INDEX processing_jobs_statement_idx
        ON processing_jobs (statement_id, created_at DESC)
        """
    )


def downgrade() -> None:
    op.drop_constraint(
        "processing_jobs_predecessor_unique",
        "processing_jobs",
        type_="unique",
    )
    op.drop_constraint(
        "processing_jobs_predecessor_fk",
        "processing_jobs",
        type_="foreignkey",
    )
    op.drop_column("processing_jobs", "predecessor_job_id")
    op.drop_constraint(
        "processing_jobs_statement_fk",
        "processing_jobs",
        type_="foreignkey",
    )
    op.drop_index("processing_jobs_statement_idx", table_name="processing_jobs")
    op.drop_table("statements")
