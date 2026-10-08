from datetime import timedelta

from bank_statement_assistant.jobs.retry import RetryPolicy


def test_retry_policy_uses_exponential_backoff_and_stops_at_the_limit() -> None:
    policy = RetryPolicy(max_attempts=3, base_delay=timedelta(seconds=5))

    assert policy.delay_after(attempt=1) == timedelta(seconds=5)
    assert policy.delay_after(attempt=2) == timedelta(seconds=10)
    assert policy.delay_after(attempt=3) is None
