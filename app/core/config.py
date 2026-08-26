from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """앱 전역 설정 — 환경변수 또는 프로젝트 루트의 .env에서 읽는다."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    openai_api_key: str = ""
    openai_model: str = "gpt-5-mini"
    finlife_api_key: str = ""
    langsmith_tracing: bool = False
    langsmith_api_key: str = ""
    database_url: str = "sqlite:///./data/app.db"
    demo_username: str = "demo"
    demo_password: str = "demo1234!"


@lru_cache
def get_settings() -> Settings:
    return Settings()
