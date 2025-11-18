from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "tg-events"
    app_env: str = "dev"
    log_level: str = "INFO"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    # Database
    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str = "tg_events"
    db_user: str = "tg"
    db_password: str = "tg"
    # Telegram
    telegram_api_id: int | None = None
    telegram_api_hash: str | None = None
    telegram_session_path: str = "sessions/user.session"
    media_root: str = "media"
    # AI / OpenAI
    openai_api_key: str | None = None  # from env: OPENAI_API_KEY
    ai_model: str = "gpt-5-nano"
    ai_fallback_model: str = "gpt-4o-mini"
    ai_timeout_s: int = 20
    ai_max_concurrency: int = 4
    ai_comment_max_chars: int = 2000

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


