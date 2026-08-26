from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

import app.api.chat as chat_module
from app.api.main import create_app
from app.core.auth_context import is_authenticated
from app.db.base import make_engine


class FakeAgent:
    """항상 정해진 답을 돌려주는 가짜 그래프. 호출 시점의 인증 컨텍스트도 기록한다."""

    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.calls: list[dict[str, Any]] = []

    def invoke(self, payload: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(
            {"payload": payload, "config": config, "authenticated": is_authenticated()}
        )
        return {"messages": [AIMessage(content=self.reply)]}


@pytest.fixture
def fake_agent(monkeypatch: pytest.MonkeyPatch) -> FakeAgent:
    agent = FakeAgent("공시월 202608 기준 안내입니다")
    monkeypatch.setattr(chat_module, "get_agent", lambda: agent)
    return agent


@pytest.fixture
def client(fake_agent: FakeAgent) -> Iterator[TestClient]:
    app = create_app(engine=make_engine("sqlite://"))
    with TestClient(app) as test_client:
        yield test_client


def test_데모_계정으로_로그인하면_토큰을_받는다(client: TestClient) -> None:
    response = client.post("/api/auth/login", json={"username": "demo", "password": "demo1234!"})
    assert response.status_code == 200
    assert len(response.json()["token"]) >= 32


def test_틀린_비밀번호는_401(client: TestClient) -> None:
    response = client.post("/api/auth/login", json={"username": "demo", "password": "nope"})
    assert response.status_code == 401


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


def test_답변의_개인정보는_마스킹되어_나간다(client: TestClient, fake_agent: FakeAgent) -> None:
    fake_agent.reply = "고객님 번호 900101-1234567 확인했습니다"
    response = client.post("/api/chat", json={"message": "내 정보 알려줘"})
    assert "900101-1234567" not in response.json()["reply"]


def test_비로그인_요청은_비인증_컨텍스트로_실행된다(
    client: TestClient, fake_agent: FakeAgent
) -> None:
    client.post("/api/chat", json={"message": "신용대출 금리"})
    assert fake_agent.calls[-1]["authenticated"] is False


def test_로그인한_요청은_인증_컨텍스트로_실행된다(
    client: TestClient, fake_agent: FakeAgent
) -> None:
    token = client.post(
        "/api/auth/login", json={"username": "demo", "password": "demo1234!"}
    ).json()["token"]
    client.post(
        "/api/chat",
        json={"message": "신용대출 금리"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert fake_agent.calls[-1]["authenticated"] is True


def test_에이전트가_실패하면_502와_안내_메시지를_준다(
    client: TestClient, fake_agent: FakeAgent, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(payload: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("LLM down")

    monkeypatch.setattr(fake_agent, "invoke", boom)
    response = client.post("/api/chat", json={"message": "안녕"})
    assert response.status_code == 502
    assert "오류" in response.json()["detail"]


def test_대화_이력을_세션별로_조회한다(client: TestClient) -> None:
    session_id = client.post("/api/chat", json={"message": "안녕"}).json()["session_id"]
    response = client.get(f"/api/history/{session_id}")
    assert response.status_code == 200
    roles = [m["role"] for m in response.json()["messages"]]
    assert roles == ["user", "assistant"]
