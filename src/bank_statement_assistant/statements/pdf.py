from io import BytesIO

from pypdf import PdfReader
from pypdf.errors import PdfReadError, PyPdfError

from bank_statement_assistant.statements.models import ExtractedPage, PdfEnvelope


class SafePdfReader:
    def __init__(self, *, max_bytes: int, max_pages: int) -> None:
        if max_bytes < 1 or max_pages < 1:
            raise ValueError("PDF limits must be positive")
        self._max_bytes = max_bytes
        self._max_pages = max_pages

    def inspect(self, *, original_filename: str, content: bytes) -> PdfEnvelope:
        if not original_filename.casefold().endswith(".pdf"):
            raise ValueError("filename must end in .pdf")
        if not content.startswith(b"%PDF-"):
            raise ValueError("content is not a PDF")
        if len(content) > self._max_bytes:
            raise ValueError("PDF exceeds the upload limit")
        reader = self._open_readable(content)
        page_count = len(reader.pages)
        if page_count < 1:
            raise ValueError("PDF must contain at least one page")
        if page_count > self._max_pages:
            raise ValueError("PDF exceeds the page limit")
        return PdfEnvelope(page_count=page_count)

    def extract_text(self, *, content: bytes) -> tuple[ExtractedPage, ...]:
        reader = self._open_readable(content)
        return tuple(
            ExtractedPage(
                number=number,
                text=_layout_text(page),
            )
            for number, page in enumerate(reader.pages, start=1)
        )

    @staticmethod
    def _open(content: bytes) -> PdfReader:
        try:
            return PdfReader(BytesIO(content), strict=True)
        except PdfReadError as error:
            raise ValueError("content is not a readable PDF") from error

    @classmethod
    def _open_readable(cls, content: bytes) -> PdfReader:
        reader = cls._open(content)
        if not reader.is_encrypted:
            return reader
        try:
            decrypted = reader.decrypt("")
        except PyPdfError as error:
            raise ValueError("encrypted PDFs are not supported") from error
        if not decrypted:
            raise ValueError("encrypted PDFs are not supported")
        return reader


def _layout_text(page: object) -> str:
    """Preserve columns where possible; synthetic blank pages have no content stream."""
    try:
        return page.extract_text(extraction_mode="layout") or ""  # type: ignore[attr-defined]
    except KeyError:
        return page.extract_text() or ""  # type: ignore[attr-defined]
