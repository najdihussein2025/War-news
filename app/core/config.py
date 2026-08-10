from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str
    gemini_api_key: str
    telegram_api_id: str | None = None
    telegram_api_hash: str | None = None
    poll_interval_minutes: int = 5

    class Config:
        env_file = ".env"


settings = Settings()
