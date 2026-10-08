from io import BytesIO

import pytest
from pypdf import PdfWriter

from bank_statement_assistant.statements.pdf import SafePdfReader


def make_pdf(
    *,
    pages: int = 1,
    user_password: str | None = None,
    owner_password: str | None = None,
) -> bytes:
    output = BytesIO()
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=612, height=792)
    if user_password is not None:
        writer.encrypt(user_password=user_password, owner_password=owner_password)
    writer.write(output)
    return output.getvalue()


def test_inspect_accepts_a_bounded_unencrypted_pdf() -> None:
    reader = SafePdfReader(max_bytes=1_000_000, max_pages=3)

    envelope = reader.inspect(original_filename="statement.PDF", content=make_pdf(pages=2))

    assert envelope.page_count == 2


@pytest.mark.parametrize(
    ("filename", "content", "message"),
    [
        ("statement.txt", b"%PDF-1.4", "filename must end in .pdf"),
        ("statement.pdf", b"not a PDF", "content is not a PDF"),
        ("statement.pdf", b"%PDF-" + b"x" * 100, "PDF exceeds the upload limit"),
    ],
)
def test_inspect_rejects_unsafe_envelopes(
    filename: str,
    content: bytes,
    message: str,
) -> None:
    reader = SafePdfReader(max_bytes=32, max_pages=3)

    with pytest.raises(ValueError, match=message):
        reader.inspect(original_filename=filename, content=content)


def test_inspect_accepts_empty_password_encryption_for_inspection_and_extraction() -> None:
    reader = SafePdfReader(max_bytes=1_000_000, max_pages=2)
    content = make_pdf(user_password="", owner_password="owner-only")

    envelope = reader.inspect(original_filename="statement.pdf", content=content)
    pages = reader.extract_text(content=content)

    assert envelope.page_count == 1
    assert [(page.number, page.text) for page in pages] == [(1, "")]


def test_inspect_rejects_real_password_encryption_and_overlong_documents() -> None:
    reader = SafePdfReader(max_bytes=1_000_000, max_pages=1)

    with pytest.raises(ValueError, match="encrypted PDFs are not supported"):
        reader.inspect(original_filename="locked.pdf", content=make_pdf(user_password="secret"))
    with pytest.raises(ValueError, match="PDF exceeds the page limit"):
        reader.inspect(original_filename="long.pdf", content=make_pdf(pages=2))


def test_extract_returns_one_stable_entry_per_page() -> None:
    reader = SafePdfReader(max_bytes=1_000_000, max_pages=3)

    pages = reader.extract_text(content=make_pdf(pages=2))

    assert [(page.number, page.text) for page in pages] == [(1, ""), (2, "")]
