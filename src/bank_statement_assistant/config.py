from pathlib import Path
from typing import Literal, Self

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

APPLICATION_VERSION = "0.1.0"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="BSA_",
        extra="ignore",
    )

    database_url: str = Field(min_length=1)
    statement_files_path: Path = Path("/var/lib/bank-statement-assistant/statements")
    static_files_path: Path | None = None
    log_level: str = "INFO"
    worker_poll_seconds: float = Field(default=1.0, gt=0)
    job_retry_delay_seconds: float = Field(default=5, ge=0)
    job_max_attempts: int = Field(default=3, ge=1)
    job_lease_seconds: int = Field(default=1000, ge=1)
    job_handler_timeout_seconds: float = Field(default=900, gt=0)
    application_version: str = Field(default=APPLICATION_VERSION, min_length=1)
    max_pdf_bytes: int = Field(default=15 * 1024 * 1024, ge=1)
    max_pdf_pages: int = Field(default=50, ge=1)
    inference_base_url: str = "http://vllm:8000/v1"
    inference_model: str = "bank-statement-qwen"
    inference_timeout_seconds: float = Field(default=120, gt=0)
    classification_batch_size: int = Field(default=20, ge=1, le=50)
    classification_research_enabled: bool = False
    search_provider: Literal["disabled", "brave", "browser"] = "brave"
    search_base_url: str = "https://api.search.brave.com/res/v1/web/search"
    search_api_key: str | None = None
    search_timeout_seconds: float = Field(default=8, gt=0)
    search_max_results: int = Field(default=5, ge=1, le=10)
    search_cache_ttl_seconds: float = Field(default=604800, gt=0)
    browser_search_base_url: str = "https://html.duckduckgo.com/html/"
    browser_search_timeout_seconds: float = Field(default=20, gt=0)
    browser_search_executable_path: str | None = None

    @model_validator(mode="after")
    def lease_outlives_stage_timeout(self) -> Self:
        if self.job_lease_seconds <= self.job_handler_timeout_seconds:
            raise ValueError("job lease must outlive the stage timeout")
        return self
