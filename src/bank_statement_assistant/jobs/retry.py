from dataclasses import dataclass
from datetime import timedelta


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    max_attempts: int
    base_delay: timedelta

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        if self.base_delay < timedelta(0):
            raise ValueError("base_delay must not be negative")

    def delay_after(self, *, attempt: int) -> timedelta | None:
        if attempt < 1:
            raise ValueError("attempt must be positive")
        if attempt >= self.max_attempts:
            return None
        return timedelta(seconds=self.base_delay.total_seconds() * (2 ** (attempt - 1)))
