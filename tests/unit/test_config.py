import pytest
from pydantic_settings import SettingsConfigDict

from app.core.config import Settings, get_settings


class SettingsWithoutDotenv(Settings):
    """개발자 로컬 .env가 테스트 결과에 끼어들지 않도록 env_file을 끈다."""

    model_config = SettingsConfigDict(env_file=None)


def test_기본값은_빈_키와_기본_모델을_가진다() -> None:
    settings = SettingsWithoutDotenv()
    assert settings.openai_api_key == ""
    assert settings.openai_model == "gpt-5-mini"
    assert settings.finlife_api_key == ""
    assert settings.langsmith_tracing is False


def test_환경변수가_기본값을_덮어쓴다(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_MODEL", "gpt-custom")
    settings = SettingsWithoutDotenv()
    assert settings.openai_model == "gpt-custom"


def test_get_settings는_같은_인스턴스를_반환한다() -> None:
    assert get_settings() is get_settings()
