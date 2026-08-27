from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_DEFAULT_DATABASE_URL = "sqlite:///./data/app.db"


class Settings(BaseSettings):
    """앱 전역 설정 — 환경변수 또는 프로젝트 루트의 .env에서 읽는다."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    openai_api_key: str = ""
    openai_model: str = "gpt-5-mini"
    finlife_api_key: str = ""
    langsmith_tracing: bool = False
    langsmith_api_key: str = ""
    database_url: str = _DEFAULT_DATABASE_URL

    @field_validator("database_url")
    @classmethod
    def _empty_database_url_falls_back(cls, value: str) -> str:
        """.env에 `DATABASE_URL=`처럼 빈 값이 있으면 기본 SQLite로 폴백한다."""
        return value.strip() or _DEFAULT_DATABASE_URL


@lru_cache
def get_settings() -> Settings:
    return Settings()
