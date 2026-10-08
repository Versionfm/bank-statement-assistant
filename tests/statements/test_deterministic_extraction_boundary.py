from pathlib import Path


def test_statement_extraction_module_has_no_network_model_client() -> None:
    source = Path("src/bank_statement_assistant/statements/extraction.py").read_text(
        encoding="utf-8"
    )

    assert "OpenAIStatementExtractor" not in source
    assert "chat/completions" not in source
    assert "urlopen" not in source
