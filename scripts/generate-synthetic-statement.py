#!/usr/bin/env python3
"""Generate a tiny, text-based PDF for local smoke testing."""

import argparse
from pathlib import Path

from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
    )
    lines = (
        "Synthetic Bank Statement",
        "Account Holder: Ana Example",
        "Statement Reference: synthetic-smoke-final",
        "Currency: EUR",
        "Opening Balance: 100.00",
        "Transaction Count: 1",
        "2026-08-02 Groceries -20.00 EUR",
        "Closing Balance: 80.00",
    )
    commands = ["BT", "/F1 12 Tf", "72 720 Td"]
    for index, line in enumerate(lines):
        if index:
            commands.append("0 -22 Td")
        commands.append(f"({line}) Tj")
    commands.append("ET")
    stream = DecodedStreamObject()
    stream.set_data("\n".join(commands).encode("ascii"))
    page[NameObject("/Contents")] = writer._add_object(stream)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("wb") as output:
        writer.write(output)


if __name__ == "__main__":
    main()
