import socket

from pytest import MonkeyPatch

from bank_statement_assistant.statements.configured_parser import build_statement_extractor
from bank_statement_assistant.statements.models import ExtractedPage


def test_configured_parser_extracts_bpi_without_network_access(monkeypatch: MonkeyPatch) -> None:
    def unexpected_network(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("deterministic parsing must not open a network connection")

    monkeypatch.setattr(socket, "create_connection", unexpected_network)
    pages = (
        ExtractedPage(
            number=1,
            text="\n".join(
                (
                    "EXTRACTO INTEGRADO",
                    "Período De 01/09/2025 a 30/09/2025",
                    "CONTA AGE Nº: 123 EUR",
                    "DEPÓSITOS À ORDEM",
                    "SALDO ANTERIOR CONTABILISTICO 10,00",
                    "01/09 01/09 Mercado -2,00 8,00",
                    "SALDO ACTUAL CONTABILISTICO 8,00",
                )
            ),
        ),
    )

    extraction = build_statement_extractor().extract(pages)

    assert extraction.provenance.extraction_strategy == "deterministic"
    assert extraction.provenance.detected_bank == "bpi"
