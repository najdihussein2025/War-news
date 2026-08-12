from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str
    telegram_api_id: str | None = None
    telegram_api_hash: str | None = None
    cnrs_api_key: str | None = None
    cnrs_api_base_url: str = "https://lebanon.cnrs.edu.lb/api/v1/inspected-posts"
    ollama_base_url: str
    ollama_api_key: str
    ollama_model: str
    ollama_timeout_seconds: int = 60
    ollama_max_concurrent_requests: int = 4
    ingestion_poll_interval_seconds: int = 120
    poll_interval_minutes: int = 5
    auth_secret_key: str = "development-only-change-me"

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
