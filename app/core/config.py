from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str
    telegram_api_id: str | None = None
    telegram_api_hash: str | None = None
    cnrs_api_key: str | None = None
    cnrs_api_base_url: str = "https://lebanon.cnrs.edu.lb/api/v1/inspected-posts"
    cnrs_webhook_secret: str
    ollama_base_url: str = "http://192.168.40.25:11435/ollama"
    ollama_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("OLLAMA_BEARER_TOKEN", "OLLAMA_API_KEY"),
    )
    ollama_model: str = "gpt-oss:20b"
    ollama_timeout_seconds: int = 90
    ollama_max_concurrent_requests: int = 4
    relevance_ollama_model: str = "gpt-oss:20b"
    extraction_ollama_model: str = "qwen2.5:7b"
    relevance_llm_batch_size: int = 4
    relevance_llm_timeout_seconds: int = 240
    relevance_classifier_backend: str = "local_llm"
    relevance_classifier_max_retries: int = 3
    relevance_classifier_retry_backoff_seconds: float = 1.0
    ingestion_poll_interval_seconds: int = 120
    poll_interval_minutes: int = 5
    login_max_failed_attempts: int = 3
    login_lockout_minutes: int = 5
    auth_secret_key: str = "development-only-change-me"
    super_admin_seed_password: str = "password"
    cluster_time_window_minutes: int = 90
    cluster_similarity_threshold: float = 0.90
    cluster_require_condition_match: bool = True

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
