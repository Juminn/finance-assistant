from typing import Any

from langchain_core.messages import HumanMessage

from app.agents.graph import (
    AgentState,
    IntentDecision,
    build_graph,
    out_of_scope,
    route_by_intent,
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
