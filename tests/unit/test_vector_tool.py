"""조건 검색 도구 — 게이트·권한·오류 처리 검증."""

from typing import Any

import pytest
from pydantic_settings import SettingsConfigDict

import app.agents.tools as tools_module
from app.agents.tools import search_products_by_condition
from app.core.auth_context import authenticated_request
from app.core.config import Settings
from app.db.vector_models import ProductEmbedding


class FakeSettings(Settings):
    model_config = SettingsConfigDict(env_file=None)


@pytest.fixture
def ready_backend(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """postgres·키·색인이 준비된 상태를 흉내내고 호출 기록을 남긴다."""
    calls: dict[str, Any] = {"embed": 0, "search_kwargs": None, "results": []}

    monkeypatch.setattr(tools_module, "get_settings", lambda: FakeSettings(openai_api_key="k"))
    monkeypatch.setattr(tools_module, "vector_search_enabled", lambda: True)
    monkeypatch.setattr(tools_module, "_openai_client", lambda: object())

    class FakeSession:
        def __enter__(self) -> "FakeSession":
            return self

        def __exit__(self, *args: Any) -> None:
            return None

    def fake_index_ready(db: Any) -> bool:
        return True

    monkeypatch.setattr(tools_module, "get_session_factory", lambda: FakeSession)
    monkeypatch.setattr(tools_module, "index_ready", fake_index_ready)

    def fake_embed(client: Any, texts: list[str], **kwargs: Any) -> list[list[float]]:
        calls["embed"] += 1
        return [[0.0] * 1536 for _ in texts]

    monkeypatch.setattr(tools_module, "embed_texts", fake_embed)

    def fake_search(db: Any, vector: list[float], **kwargs: Any) -> list[Any]:
        calls["search_kwargs"] = kwargs
        return calls["results"]

    monkeypatch.setattr(tools_module, "search_similar", fake_search)
    return calls


def test_sqlite_환경이면_준비되지_않았다고_안내한다(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tools_module, "get_settings", lambda: FakeSettings(openai_api_key="k"))
    monkeypatch.setattr(tools_module, "vector_search_enabled", lambda: False)
    result = search_products_by_condition.invoke({"query": "급여이체 우대"})
    assert "준비" in result


def test_openai_키가_없으면_안내한다(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tools_module, "get_settings", lambda: FakeSettings(openai_api_key=""))
    monkeypatch.setattr(tools_module, "vector_search_enabled", lambda: True)
    result = search_products_by_condition.invoke({"query": "급여이체 우대"})
    assert "키" in result


def test_비로그인이_신용대출_카테고리를_지정하면_로그인_안내만_한다(
    ready_backend: dict[str, Any],
) -> None:
    result = search_products_by_condition.invoke(
        {"query": "금리 낮은 대출", "category": "개인신용대출"}
    )
    assert "로그인" in result
    assert ready_backend["embed"] == 0  # 검색 자체가 실행되지 않아야 한다


def test_비로그인_전체_검색은_신용대출을_제외한다(ready_backend: dict[str, Any]) -> None:
    search_products_by_condition.invoke({"query": "우대금리"})
    assert ready_backend["search_kwargs"]["exclude_category"] == "개인신용대출"


def test_로그인하면_신용대출_카테고리도_검색된다(ready_backend: dict[str, Any]) -> None:
    with authenticated_request(True):
        search_products_by_condition.invoke(
            {"query": "금리 낮은 신용대출", "category": "개인신용대출"}
        )
    assert ready_backend["embed"] == 1
    assert ready_backend["search_kwargs"]["category"] == "개인신용대출"
    assert ready_backend["search_kwargs"]["exclude_category"] is None


def test_색인이_비어있으면_미준비_안내를_한다(
    ready_backend: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    def empty_index(db: Any) -> bool:
        return False

    monkeypatch.setattr(tools_module, "index_ready", empty_index)
    result = search_products_by_condition.invoke({"query": "우대금리"})
    assert "준비" in result


def test_알_수_없는_카테고리는_전체_검색으로_바꾸되_결과에_명시한다(
    ready_backend: dict[str, Any],
) -> None:
    result = search_products_by_condition.invoke({"query": "우대금리", "category": "예금"})
    assert ready_backend["search_kwargs"]["category"] is None
    assert "예금" in result  # 인식 못 한 카테고리를 결과에 알린다


def test_내부_오류는_원문_노출_없이_일반_안내로_바뀐다(
    ready_backend: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    secret = "ep-secret-host.neon.tech에서 password authentication failed"

    def boom(client: Any, texts: list[str], **kwargs: Any) -> list[list[float]]:
        raise RuntimeError(secret)

    monkeypatch.setattr(tools_module, "embed_texts", boom)
    result = search_products_by_condition.invoke({"query": "우대금리"})
    assert "오류" in result
    assert "neon.tech" not in result
    assert "password" not in result


def test_검색_결과가_포맷되어_반환된다(ready_backend: dict[str, Any]) -> None:
    row = ProductEmbedding(
        product_key="deposit:A:P1",
        category="정기예금",
        bank="가은행",
        name="가예금",
        text="[정기예금] 가은행 가예금\n우대조건: 첫 거래 우대",
        content_hash="x",
        disclosure_month="202608",
        embedding=[0.0] * 1536,
    )
    ready_backend["results"] = [(row, 0.21)]
    result = search_products_by_condition.invoke({"query": "첫 거래 우대"})
    assert "가은행" in result
    assert "202608" in result


def test_카테고리를_안_줘도_질의에서_추론해_좁힌다(ready_backend: dict[str, Any]) -> None:
    with authenticated_request(True):
        result = search_products_by_condition.invoke({"query": "급여이체 우대 있는 적금"})
    assert ready_backend["search_kwargs"]["category"] == "적금"
    assert "적금" in result  # 좁혀 검색했음을 결과에 밝힌다


def test_명시한_카테고리가_추론보다_우선한다(ready_backend: dict[str, Any]) -> None:
    with authenticated_request(True):
        search_products_by_condition.invoke(
            {"query": "주택담보대출처럼 쓸 수 있는 상품", "category": "적금"}
        )
    assert ready_backend["search_kwargs"]["category"] == "적금"


def test_추론_결과가_신용대출이면_비로그인은_로그인_안내를_받는다(
    ready_backend: dict[str, Any],
) -> None:
    # 카테고리를 명시했을 때와 같은 권한 정책이 적용돼야 한다
    result = search_products_by_condition.invoke({"query": "마이너스통장 만들 수 있는 곳"})
    assert "로그인" in result
    assert ready_backend["embed"] == 0


def test_추론할_단서가_없으면_기존대로_전체를_검색한다(ready_backend: dict[str, Any]) -> None:
    search_products_by_condition.invoke({"query": "청년만 가입할 수 있는 상품"})
    assert ready_backend["search_kwargs"]["category"] is None
    assert ready_backend["search_kwargs"]["exclude_category"] == "개인신용대출"
