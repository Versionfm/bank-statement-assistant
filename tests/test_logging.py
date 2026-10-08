import logging

from bank_statement_assistant.logging import JsonFormatter


def test_json_formatter_redacts_exception_messages() -> None:
    secret = "raw transaction description"
    exception = ValueError(secret)
    record = logging.LogRecord(
        name="test",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg="job_stage_failed",
        args=(),
        exc_info=(ValueError, exception, None),
    )

    formatted = JsonFormatter().format(record)

    assert secret not in formatted
    assert '"exception_type":"ValueError"' in formatted
