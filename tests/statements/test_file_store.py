from pathlib import Path
from uuid import UUID

from bank_statement_assistant.statements.files import LocalStatementFileStore


def test_store_uses_a_generated_path_and_never_the_uploaded_filename(tmp_path: Path) -> None:
    store = LocalStatementFileStore(tmp_path)
    statement_id = UUID("50e5591f-913e-471b-a501-541fd860af30")

    path = store.store(statement_id=statement_id, content=b"%PDF safe")

    assert path == tmp_path / "50" / f"{statement_id}.pdf"
    assert path.read_bytes() == b"%PDF safe"


def test_delete_removes_a_stored_source_idempotently(tmp_path: Path) -> None:
    store = LocalStatementFileStore(tmp_path)
    statement_id = UUID("50e5591f-913e-471b-a501-541fd860af30")
    path = store.store(statement_id=statement_id, content=b"%PDF safe")

    store.delete(path=path)
    store.delete(path=path)

    assert not path.exists()
