import logging
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

import app.api.chat as chat_module
from app.api.main import create_app
from app.db.base import make_engine


class FakeAgent:
    """항상 정해진 답을 돌려주는 가짜 그래프."""

    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.calls: list[dict[str, Any]] = []

    def invoke(self, payload: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
        self.calls.append({"payload": payload, "config": config})
        return {"messages": [AIMessage(content=self.reply)]}


@pytest.fixture
def fake_agent(monkeypatch: pytest.MonkeyPatch) -> FakeAgent:
    agent = FakeAgent("공시월 202608 기준 안내입니다")
    monkeypatch.setattr(chat_module, "get_agent", lambda: agent)
    return agent


@pytest.fixture
def client(fake_agent: FakeAgent) -> Iterator[TestClient]:
    from app.db import session as session_module

    app = create_app(engine=make_engine("sqlite://"))
    with TestClient(app) as test_client:
        yield test_client
    session_module.set_engine(None)


def test_로그인_엔드포인트는_더_이상_없다(client: TestClient) -> None:
    response = client.post("/api/auth/login", json={"username": "demo", "password": "demo1234!"})
    # 라우트가 사라져 정적 마운트(/)가 요청을 받는다 — GET 전용이라 405
    assert response.status_code == 405
    assert "token" not in response.text


def test_챗_요청은_답변과_세션id를_반환한다(client: TestClient, fake_agent: FakeAgent) -> None:
    response = client.post("/api/chat", json={"message": "1년 정기예금 비교해줘"})
    assert response.status_code == 200
    body = response.json()
    assert body["reply"] == "공시월 202608 기준 안내입니다"
    assert body["session_id"]
    # 같은 세션으로 이어서 대화하면 thread_id가 유지된다
    again = client.post(
        "/api/chat", json={"message": "두 번째는?", "session_id": body["session_id"]}
    )
    assert again.json()["session_id"] == body["session_id"]
    thread_ids = [c["config"]["configurable"]["thread_id"] for c in fake_agent.calls]
    assert thread_ids[0] == thread_ids[1]


def test_세션이_다르면_스레드도_다르다(client: TestClient, fake_agent: FakeAgent) -> None:
    client.post("/api/chat", json={"message": "안녕"})
    client.post("/api/chat", json={"message": "안녕"})
    threads = [c["config"]["configurable"]["thread_id"] for c in fake_agent.calls]
    assert threads[0] != threads[1]


def test_답변의_개인정보는_마스킹되어_나간다(client: TestClient, fake_agent: FakeAgent) -> None:
    fake_agent.reply = "고객님 번호 900101-1234567 확인했습니다"
    response = client.post("/api/chat", json={"message": "내 정보 알려줘"})
    assert "900101-1234567" not in response.json()["reply"]


def test_에이전트가_실패하면_502와_안내_메시지를_준다(
    client: TestClient, fake_agent: FakeAgent, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(payload: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("LLM down")

    monkeypatch.setattr(fake_agent, "invoke", boom)
    response = client.post("/api/chat", json={"message": "안녕"})
    assert response.status_code == 502
    assert "오류" in response.json()["detail"]


def test_실패_로그에_세션id_전문이_남지_않는다(
    client: TestClient,
    fake_agent: FakeAgent,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # 로그인을 없앤 뒤로 session_id가 대화를 여는 유일한 비밀이다.
    # 로그를 보는 사람이 남의 대화를 열 수 있으면 안 된다.
    def boom(payload: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("LLM down")

    monkeypatch.setattr(fake_agent, "invoke", boom)
    session_id = "0123456789abcdef0123456789abcdef"
    with caplog.at_level(logging.ERROR):
        client.post("/api/chat", json={"message": "안녕", "session_id": session_id})

    assert session_id not in caplog.text


def test_대화_이력을_세션별로_조회한다(client: TestClient) -> None:
    session_id = client.post("/api/chat", json={"message": "안녕"}).json()["session_id"]
    response = client.get(f"/api/history/{session_id}")
    assert response.status_code == 200
    roles = [m["role"] for m in response.json()["messages"]]
    assert roles == ["user", "assistant"]
