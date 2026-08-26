"""벡터 검색 도구 — 저장소가 준비되지 않았을 때의 동작 검증."""

import pytest
from pydantic_settings import SettingsConfigDict

from app.agents.tools import search_products_by_condition
from app.core.config import Settings


class FakeSettings(Settings):
    model_config = SettingsConfigDict(env_file=None)


def test_sqlite_환경이면_준비되지_않았다고_안내한다(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.agents.tools.get_settings",
        lambda: FakeSettings(database_url="sqlite:///./data/app.db", openai_api_key="k"),
    )
    result = search_products_by_condition.invoke({"query": "급여이체 우대"})
    assert "준비" in result


def test_openai_키가_없으면_안내한다(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.agents.tools.get_settings",
        lambda: FakeSettings(database_url="postgresql://u:p@host/db", openai_api_key=""),
    )
    result = search_products_by_condition.invoke({"query": "급여이체 우대"})
    assert "키" in result
