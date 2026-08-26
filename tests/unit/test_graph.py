from typing import Any

from langchain_core.messages import HumanMessage

from app.agents.graph import (
    AgentState,
    IntentDecision,
    build_graph,
    route_by_intent,
    supervisor,
)


def make_state(intent: str = "") -> AgentState:
    state: AgentState = {"messages": [HumanMessage("안녕")], "intent": intent}  # type: ignore[typeddict-item]
    return state


def test_의도별로_해당_워커_노드로_라우팅한다() -> None:
    assert route_by_intent(make_state("deposit")) == "deposit"
    assert route_by_intent(make_state("loan")) == "loan"
    assert route_by_intent(make_state("general")) == "general"


def test_의도가_비어있으면_general로_보낸다() -> None:
    assert route_by_intent(make_state("")) == "general"


def test_그래프에_supervisor와_워커_노드가_모두_있다() -> None:
    graph = build_graph()
    nodes = set(graph.get_graph().nodes)
    assert {"supervisor", "deposit", "loan", "general"} <= nodes


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
