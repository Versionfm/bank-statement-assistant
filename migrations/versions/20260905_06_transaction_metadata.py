"""Add editable counterparty and note metadata to transactions."""

from alembic import op

revision = "20260905_06"
down_revision = "20260905_05"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE transactions ADD COLUMN counterparty text;
        ALTER TABLE transactions ADD COLUMN note text;
        ALTER TABLE transaction_corrections ADD COLUMN counterparty text;
        ALTER TABLE transaction_corrections ADD COLUMN note text;
        ALTER TABLE transaction_corrections ADD CONSTRAINT
            transaction_corrections_classification_changed_check CHECK (
                NOT classification_changed OR movement_kind IS NOT NULL
            );
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE transaction_corrections DROP CONSTRAINT
            transaction_corrections_classification_changed_check;
        ALTER TABLE transaction_corrections DROP COLUMN note;
        ALTER TABLE transaction_corrections DROP COLUMN counterparty;
        ALTER TABLE transactions DROP COLUMN note;
        ALTER TABLE transactions DROP COLUMN counterparty;
        """
    )
