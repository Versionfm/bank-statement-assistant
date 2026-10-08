from pathlib import Path

from bank_statement_assistant.schema import SCHEMA_HEAD


def test_schema_head_creates_durable_statement_state() -> None:
    migration = Path("migrations/versions/20260902_02_statements.py").read_text()

    assert SCHEMA_HEAD == "20260906_09"
    assert "CREATE TABLE statements" in migration
    assert "content_hash text NOT NULL UNIQUE" in migration
    assert "extracted_pages jsonb" in migration
    assert "extraction_result jsonb" in migration
    assert "validation_result jsonb" in migration
    assert "review_findings jsonb" in migration
    assert 'revision = "20260902_02"' in migration
    assert "processing_jobs_statement_fk" in migration
    assert "VALIDATE CONSTRAINT processing_jobs_statement_fk" in migration
    assert "processing_jobs_predecessor_unique" in migration


def test_transaction_migration_persists_candidates_and_backfills_legacy_json() -> None:
    migration = Path("migrations/versions/20260903_03_transactions.py").read_text()

    assert "CREATE TABLE transactions" in migration
    assert "CREATE TABLE review_findings" in migration
    assert "extraction_result->'transactions'" in migration
    assert "jsonb_array_elements" in migration
    assert "source_identity" in migration
    assert "transactions_statement_ordinal_unique" in migration


def test_classification_migration_persists_decisions_and_provenance() -> None:
    migration = Path("migrations/versions/20260904_04_classification.py").read_text()

    assert "reporting_category" in migration
    assert "movement_kind" in migration
    assert "payment_channel" in migration
    assert "classification_status" in migration
    assert "classification_confidence" in migration
    assert "classification_provenance" in migration
    assert "CREATE TABLE transaction_classifications" in migration
    assert "transaction_classifications_complete_check" in migration


def test_resolution_migration_preserves_corrections_and_review_history() -> None:
    migration = Path("migrations/versions/20260905_05_transaction_resolution.py").read_text()

    assert "CREATE TABLE transaction_corrections" in migration
    assert "transaction_corrections_transaction_revision_unique" in migration
    assert "CREATE TABLE transaction_classification_reviews" in migration
    assert "CREATE TABLE statement_validation_runs" in migration
    assert "'revalidate'" in migration


def test_metadata_migration_adds_editable_counterparty_and_note() -> None:
    migration = Path("migrations/versions/20260905_06_transaction_metadata.py").read_text()

    assert 'revision = "20260905_06"' in migration
    assert "ALTER TABLE transactions ADD COLUMN counterparty" in migration
    assert "ALTER TABLE transaction_corrections ADD COLUMN note" in migration


def test_transfer_scope_migration_supports_internal_and_external_flow() -> None:
    migration = Path("migrations/versions/20260905_07_transfer_scope.py").read_text()

    assert 'revision = "20260905_07"' in migration
    assert "ALTER TABLE transactions ADD COLUMN transfer_scope" in migration
    assert "ALTER TABLE transaction_corrections ADD COLUMN transfer_scope" in migration
    assert "own_account" in migration
    assert "external_party" in migration
    assert "movement_kind = 'Transfer'" in migration


def test_merchant_evidence_migration_supports_replayable_research() -> None:
    migration = Path("migrations/versions/20260906_08_merchant_evidence.py").read_text()

    assert 'revision = "20260906_08"' in migration
    assert "CREATE TABLE merchant_evidence_cache" in migration
    assert "normalized_key text PRIMARY KEY" in migration
    assert "response_hash" in migration
    assert "expires_at" in migration


def test_correction_proposal_migration_is_non_binding_and_idempotent() -> None:
    migration = Path("migrations/versions/20260906_09_correction_proposals.py").read_text()

    assert 'revision = "20260906_09"' in migration
    assert "CREATE TABLE transaction_correction_proposals" in migration
    assert "before_values jsonb NOT NULL" in migration
    assert "proposed_changes jsonb NOT NULL" in migration
    assert "model text NOT NULL" in migration
    assert "prompt_version text NOT NULL" in migration
    assert "idempotency_key text NOT NULL UNIQUE" in migration
    assert "status IN ('pending', 'accepted', 'rejected')" in migration
