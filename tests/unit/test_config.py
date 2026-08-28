import pytest
from pydantic_settings import SettingsConfigDict

from app.core.config import Settings, get_settings

_ENV_KEYS = (
    "OPENAI_API_KEY",
    "OPENAI_MODEL",
    "FINLIFE_API_KEY",
    "LANGSMITH_TRACING",
    "LANGSMITH_API_KEY",
    "DATABASE_URL",
)


class SettingsWithoutDotenv(Settings):
    """개발자 로컬 .env가 테스트 결과에 끼어들지 않도록 env_file을 끈다."""

    model_config = SettingsConfigDict(env_file=None)


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """다른 테스트(load_dotenv 등)가 올려둔 환경변수까지 걷어낸다."""
    for key in _ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def test_기본값은_빈_키와_기본_모델을_가진다(clean_env: None) -> None:
    settings = SettingsWithoutDotenv()
    assert settings.openai_api_key == ""
    assert settings.openai_model == "gpt-5-mini"
    assert settings.finlife_api_key == ""
    assert settings.langsmith_tracing is False


def test_환경변수가_기본값을_덮어쓴다(clean_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_MODEL", "gpt-custom")
    settings = SettingsWithoutDotenv()
    assert settings.openai_model == "gpt-custom"


def test_get_settings는_같은_인스턴스를_반환한다() -> None:
    assert get_settings() is get_settings()


def test_DATABASE_URL이_빈_값이면_기본_SQLite로_폴백한다(
    clean_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DATABASE_URL", "")
    settings = SettingsWithoutDotenv()
    assert settings.database_url == "sqlite:///./data/app.db"


def test_DATABASE_URL_공백만_있어도_기본값으로_폴백한다(
    clean_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DATABASE_URL", "   ")
    settings = SettingsWithoutDotenv()
    assert settings.database_url == "sqlite:///./data/app.db"
