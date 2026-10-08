from bank_statement_assistant.config import Settings


def test_defaults_support_deterministic_statement_processing() -> None:
    settings = Settings(
        database_url="postgresql+psycopg://example.invalid/statements",
        _env_file=None,
    )

    assert settings.job_handler_timeout_seconds == 900
    assert settings.job_lease_seconds == 1000
    assert settings.job_lease_seconds > settings.job_handler_timeout_seconds
    assert settings.application_version == "0.1.0"
    assert settings.max_pdf_pages == 50
    assert settings.classification_research_enabled is False
    assert settings.search_provider == "brave"
    assert settings.search_max_results == 5
    assert settings.search_cache_ttl_seconds == 604800
    assert settings.browser_search_timeout_seconds == 20
