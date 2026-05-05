from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache


class Settings(BaseSettings):
    openai_api_key: str
    database_url: str = "sqlite:///./vendor_onboarding.db"
    chroma_persist_path: str = "./chroma_db"
    log_level: str = "INFO"

    # Gmail poller
    gmail_enabled: bool = False
    gmail_poll_interval: int = 30
    gmail_credentials_file: str = "./scripts/credentials.json"
    gmail_token_file: str = "./scripts/token.json"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8-sig")


@lru_cache
def get_settings() -> Settings:
    return Settings()
