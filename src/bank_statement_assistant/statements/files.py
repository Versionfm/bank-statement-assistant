import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from uuid import UUID


class LocalStatementFileStore:
    """Stores immutable PDF sources under paths generated from statement IDs."""

    def __init__(self, root: Path) -> None:
        self._root = root

    def store(self, *, statement_id: UUID, content: bytes) -> Path:
        directory = self._root / statement_id.hex[:2]
        directory.mkdir(parents=True, exist_ok=True)
        destination = directory / f"{statement_id}.pdf"
        if destination.exists():
            raise FileExistsError(f"statement source already exists: {statement_id}")
        with NamedTemporaryFile(dir=directory, prefix=".upload-", delete=False) as temporary:
            temporary.write(content)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_path = Path(temporary.name)
        try:
            temporary_path.replace(destination)
        except Exception:
            temporary_path.unlink(missing_ok=True)
            raise
        return destination

    def delete(self, *, path: Path) -> None:
        path.unlink(missing_ok=True)
