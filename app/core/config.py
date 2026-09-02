from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str
    telegram_api_id: str | None = None
    telegram_api_hash: str | None = None
    telegram_session_string: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "TELEGRAM_SESSION_STRING",
            "RED_ALERT_TELEGRAM_SESSION_STRING",
        ),
    )
    red_alert_enabled: bool = False
    red_alert_delivery_method: str = "public_preview"
    red_alert_channel_username: str = "redlinkleb"
    red_alert_fetch_limit: int = 20
    red_alert_poll_seconds: float = 10.0
    red_alert_request_timeout_seconds: int = 30
    red_alert_ocr_enabled: bool = True
    cnrs_api_key: str | None = None
    cnrs_api_base_url: str = "https://lebanon.cnrs.edu.lb/api/v1/llm-filtered-posts"
    cnrs_lookback_hours: int = 48
    cnrs_webhook_secret: str
    air_violation_webhook_enabled: bool = False
    air_violation_webhook_url: str | None = None
    air_violation_webhook_timeout_seconds: int = 10
    air_violation_webhook_secret: str | None = None
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
    extraction_llm_timeout_seconds: int = 240
    extraction_llm_max_concurrent_requests: int = 2
    # Independent Tier 1 / Tier 2 LLM concurrency pools (see ollama_concurrency.py).
    tier1_llm_max_concurrent_requests: int = 2
    tier2_llm_max_concurrent_requests: int = 2
    extraction_llm_request_retries: int = 2
    extraction_llm_retry_backoff_seconds: float = 2.0
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
    # Look-back window for pre-extraction dedup comparisons (hours).
    pre_dedup_window_hours: int = 48
    # Candidate narrowing before word_similarity(): none | same_source |
    # same_source_time_bucket (env: PRE_DEDUP_CANDIDATE_NARROWING).
    pre_dedup_candidate_narrowing: str = "same_source"
    # Half-width of the optional time bucket around the candidate received_at (hours).
    pre_dedup_time_bucket_hours: int = 6
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
    pipeline_claim_lease_seconds: int = 240
    extraction_max_retries: int = 5
    matching_max_retries: int = 5
    redis_url: str = "redis://redis:6379/0"
    cache_enabled: bool = True

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
