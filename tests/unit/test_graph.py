from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.memory import MemorySaver

from app.agents.graph import (
    HISTORY_WINDOW,
    AgentState,
    IntentDecision,
    build_graph,
    history_for_llm,
    out_of_scope,
    route_by_intent,
    run_worker,
    supervisor,
)
from app.agents.prompts import OUT_OF_SCOPE_REPLY


def make_state(intent: str = "") -> AgentState:
    state: AgentState = {"messages": [HumanMessage("안녕")], "intent": intent}  # type: ignore[typeddict-item]
    return state


def test_의도별로_해당_워커_노드로_라우팅한다() -> None:
    assert route_by_intent(make_state("deposit")) == "deposit"
    assert route_by_intent(make_state("loan")) == "loan"
    assert route_by_intent(make_state("general")) == "general"
    assert route_by_intent(make_state("out_of_scope")) == "out_of_scope"


def test_의도가_비어있으면_general로_보낸다() -> None:
    assert route_by_intent(make_state("")) == "general"


def test_그래프에_supervisor와_워커_노드가_모두_있다() -> None:
    graph = build_graph()
    nodes = set(graph.get_graph().nodes)
    assert {"supervisor", "deposit", "loan", "general", "out_of_scope"} <= nodes


class FakeStructuredModel:
    def __init__(self, intent: str) -> None:
        self._intent = intent

    def invoke(self, _messages: Any) -> IntentDecision:
        return IntentDecision(intent=self._intent)  # type: ignore[arg-type]


class FakeChatModel:
    def __init__(self, intent: str) -> None:
        self._intent = intent

    def with_structured_output(self, _schema: Any) -> FakeStructuredModel:
        return FakeStructuredModel(self._intent)


def test_supervisor는_분류_결과를_intent에_기록한다(monkeypatch: Any) -> None:
    import app.agents.graph as graph_module

    monkeypatch.setattr(graph_module, "_chat_model", lambda: FakeChatModel("deposit"))
    update = supervisor(make_state())
    assert update == {"intent": "deposit"}


def test_supervisor는_범위_밖_의도도_기록한다(monkeypatch: Any) -> None:
    import app.agents.graph as graph_module

    monkeypatch.setattr(graph_module, "_chat_model", lambda: FakeChatModel("out_of_scope"))
    assert supervisor(make_state()) == {"intent": "out_of_scope"}


class ExplodingModel:
    """호출 시점에 실패하는 모델 — API 장애·타임아웃을 흉내 낸다."""

    def with_structured_output(self, _schema: Any) -> "ExplodingModel":
        return self

    def invoke(self, _messages: Any) -> Any:
        raise RuntimeError("LLM down")


class NoneModel:
    """구조화 출력 파싱이 결과를 못 만든 경우를 흉내 낸다."""

    def with_structured_output(self, _schema: Any) -> "NoneModel":
        return self

    def invoke(self, _messages: Any) -> Any:
        return None


def test_분류_호출이_실패하면_general로_폴백한다(monkeypatch: Any) -> None:
    # 분류는 답변을 보조하는 단계다 — 여기서 죽으면 요청 전체가 502로 번진다.
    # route_by_intent가 미지 intent를 general로 보내는 것과 같은 철학으로 막는다.
    import app.agents.graph as graph_module

    monkeypatch.setattr(graph_module, "_chat_model", lambda: ExplodingModel())
    assert supervisor(make_state()) == {"intent": "general"}


def test_분류_결과가_형식에_맞지_않으면_general로_폴백한다(monkeypatch: Any) -> None:
    import app.agents.graph as graph_module

    monkeypatch.setattr(graph_module, "_chat_model", lambda: NoneModel())
    assert supervisor(make_state()) == {"intent": "general"}


def test_범위_밖_질문은_LLM을_태우지_않고_고정_문구로_거절한다(monkeypatch: Any) -> None:
    import app.agents.graph as graph_module

    def 호출되면_실패() -> None:
        raise AssertionError("범위 밖 질문에는 LLM을 호출하면 안 된다")

    monkeypatch.setattr(graph_module, "_chat_model", 호출되면_실패)
    update = out_of_scope(make_state("out_of_scope"))
    assert [m.content for m in update["messages"]] == [OUT_OF_SCOPE_REPLY]


def test_거절_문구는_대신_할_수_있는_일을_안내한다() -> None:
    # 그냥 거절만 하면 사용자가 다음에 뭘 물어야 할지 알 수 없다
    assert "정기예금" in OUT_OF_SCOPE_REPLY
    assert "대출" in OUT_OF_SCOPE_REPLY


def test_general_프롬프트는_조회_불가_상품의_추천을_막는다() -> None:
    # 보험·연금저축처럼 조회할 수 없는 상품을 고르려는 질문도 general로 온다.
    # 도구 없는 워커가 학습 지식으로 특정 상품을 답하면 "도구 결과만 사용"
    # 원칙이 이 경로에서만 뚫린다 — '투자 권유 금지'로는 보험사 추천이 안 막힌다.
    from app.agents.prompts import GENERAL_AGENT_SYSTEM

    assert "연금저축" in GENERAL_AGENT_SYSTEM
    assert "추천하지 않는다" in GENERAL_AGENT_SYSTEM


def test_챗_모델은_프로세스당_한_번만_만든다() -> None:
    # 생성 시점에 sync·async httpx 클라이언트를 즉시 만들므로, supervisor처럼
    # 모든 요청이 지나는 경로에서 매번 새로 만들면 커넥션 풀이 그대로 버려진다
    import app.agents.graph as graph_module

    chat_model = graph_module._chat_model  # pyright: ignore[reportPrivateUsage]
    chat_model.cache_clear()
    try:
        assert chat_model() is chat_model()
    finally:
        chat_model.cache_clear()


def test_전역_에이전트는_설정의_DB_URL로_체크포인터를_만든다(monkeypatch: Any) -> None:
    import app.agents.graph as graph_module

    saver = MemorySaver()
    seen: list[str] = []

    def fake_make_checkpointer(url: str) -> MemorySaver:
        seen.append(url)
        return saver

    monkeypatch.setattr(graph_module, "make_checkpointer", fake_make_checkpointer)
    graph_module.get_agent.cache_clear()
    try:
        graph_module.get_agent()
        assert seen == [graph_module.get_settings().database_url]
    finally:
        graph_module.get_agent.cache_clear()


def test_llm_입력_이력에서_도구_호출과_결과_메시지를_거른다() -> None:
    # 과거 턴의 도구 흔적이 다른 워커 LLM에 들어가면 자기에게 없는 도구를
    # 흉내 내 호출하거나 분류 입력에 상품표 전문이 실린다
    messages = [
        HumanMessage("적금 비교해줘"),
        AIMessage("", tool_calls=[{"name": "compare_saving_products", "args": {}, "id": "c1"}]),
        ToolMessage("1위 A은행 연 5.0% ...", tool_call_id="c1"),
        AIMessage("1위는 A은행 연 5.0%입니다."),
        HumanMessage("전세대출은 어때?"),
    ]
    view = history_for_llm(messages)
    assert [type(m) for m in view] == [HumanMessage, AIMessage, HumanMessage]
    assert view[1].content == "1위는 A은행 연 5.0%입니다."


def test_llm_입력_이력에서_본문이_있는_툴콜_메시지는_본문만_남긴다() -> None:
    # tool_calls가 붙은 채 보내면 대응 ToolMessage가 없어 OpenAI가 400을 낸다
    msg = AIMessage("조회해 볼게요.", tool_calls=[{"name": "t", "args": {}, "id": "c1"}])
    (only,) = history_for_llm([HumanMessage("적금?"), msg])[1:]
    assert isinstance(only, AIMessage)
    assert only.content == "조회해 볼게요."
    assert only.tool_calls == []


def test_llm_입력_이력은_최근_메시지만_남긴다() -> None:
    messages = [HumanMessage(f"질문 {i}") for i in range(HISTORY_WINDOW + 5)]
    view = history_for_llm(messages)
    assert len(view) == HISTORY_WINDOW
    assert view[-1].content == f"질문 {HISTORY_WINDOW + 4}"


class FakeWorkerAgent:
    """받은 이력을 기록하고, 도구 왕복이 섞인 결과를 돌려주는 가짜 서브에이전트."""

    def __init__(self) -> None:
        self.seen: list[Any] = []

    def invoke(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.seen = list(payload["messages"])
        return {
            "messages": [
                *self.seen,
                AIMessage("", tool_calls=[{"name": "compare", "args": {}, "id": "c9"}]),
                ToolMessage("상품표 전문", tool_call_id="c9"),
                AIMessage("최종 답변입니다."),
            ]
        }


def test_워커는_정리된_이력만_받고_최종_답변만_상태에_남긴다() -> None:
    worker = FakeWorkerAgent()
    state: AgentState = {
        "messages": [
            HumanMessage("적금 비교해줘"),
            AIMessage("", tool_calls=[{"name": "compare", "args": {}, "id": "c1"}]),
            ToolMessage("지난 턴 상품표", tool_call_id="c1"),
            AIMessage("지난 턴 답변"),
            HumanMessage("전세대출은?"),
        ],
        "intent": "loan",
    }
    update = run_worker(worker, state)

    assert not any(isinstance(m, ToolMessage) for m in worker.seen)
    assert [m.content for m in update["messages"]] == ["최종 답변입니다."]
