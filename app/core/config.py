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
    relevance_classifier_backend: str = "cnrs_provided"
    relevance_classifier_max_retries: int = 3
    relevance_classifier_retry_backoff_seconds: float = 1.0
    ingestion_poll_interval_seconds: int = 120
    poll_interval_minutes: int = 5
    login_max_failed_attempts: int = 3
    login_lockout_minutes: int = 5
    auth_secret_key: str = "development-only-change-me"
    auth_cookie_secure: bool = False
    auth_cookie_samesite: str = "lax"
    super_admin_seed_password: str = "password"
    # First-pass values derived from a single confirmed duplicate pair
    # (248 min gap, 0.7675 cosine similarity — 2026-08-18).
    # Revisit after 2–3 weeks of live backlog data to validate against a
    # full similarity/time-gap distribution before treating as permanent.
    cluster_time_window_minutes: int = 300
    cluster_similarity_threshold: float = 0.75
    cluster_require_condition_match: bool = True
    # Fast-path materialization dedup: exact village_id + condition_id match window.
    fast_dedup_time_window_minutes: int = 120
    pre_dedup_similarity_threshold: float = 0.92
    # Max pre-dedup rows processed per full sweep before tier1 starts.
    # Prevents multi-minute "frozen" sweeps on large backlogs.
    pre_dedup_sweep_row_cap: int = 100
    # Incident-level dedup thresholds and look-back window.
    # Tune after reviewing real duplicate decisions; env vars override these.
    dedup_time_window_days: int = 3
    dedup_high_threshold: float = 0.80
    dedup_low_threshold: float = 0.50
    pg_application_name: str = "war-news"
    pipeline_role: str = "api"
    pipeline_worker_poll_seconds: float = 2.0

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
