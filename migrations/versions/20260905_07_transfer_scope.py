"""Track whether transfers are internal or external to the user's accounts."""

from alembic import op

revision = "20260905_07"
down_revision = "20260905_06"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE transactions ADD COLUMN transfer_scope text;
        ALTER TABLE transaction_corrections ADD COLUMN transfer_scope text;
        ALTER TABLE transactions ADD CONSTRAINT transactions_transfer_scope_check CHECK (
            transfer_scope IS NULL OR transfer_scope IN ('own_account', 'external_party', 'unknown')
        );
        ALTER TABLE transaction_corrections ADD CONSTRAINT
            transaction_corrections_transfer_scope_check CHECK (
            (transfer_scope IS NULL OR transfer_scope IN (
                'own_account', 'external_party', 'unknown'
            ))
            AND (transfer_scope IS NULL OR movement_kind = 'Transfer')
        );
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE transaction_corrections DROP CONSTRAINT
            transaction_corrections_transfer_scope_check;
        ALTER TABLE transactions DROP CONSTRAINT transactions_transfer_scope_check;
        ALTER TABLE transaction_corrections DROP COLUMN transfer_scope;
        ALTER TABLE transactions DROP COLUMN transfer_scope;
        """
    )
