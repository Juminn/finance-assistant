"""LangGraph 멀티 에이전트 그래프 — supervisor(의도분류) + 상품군별 worker."""

# langgraph/langchain의 제네릭이 부분적으로 Unknown이라 파일 단위로만 완화한다
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false

from functools import lru_cache
from typing import Any, Literal

from langchain.agents import create_agent
from langchain_core.messages import SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.graph.state import CompiledStateGraph
from pydantic import BaseModel, SecretStr

from app.agents.prompts import (
    DEPOSIT_AGENT_SYSTEM,
    GENERAL_AGENT_SYSTEM,
    LOAN_AGENT_SYSTEM,
    SUPERVISOR_SYSTEM,
)
from app.agents.tools import (
    compare_credit_loans,
    compare_deposit_products,
    compare_mortgage_loans,
    compare_rent_loans,
    compare_saving_products,
)
from app.core.config import get_settings

Intent = Literal["deposit", "loan", "general"]


class AgentState(MessagesState):
    intent: Intent


class IntentDecision(BaseModel):
    intent: Intent


def _chat_model() -> ChatOpenAI:
    settings = get_settings()
    # 키가 없어도 그래프 구축은 가능해야 한다 (실 호출 시점에만 실패)
    return ChatOpenAI(
        model=settings.openai_model,
        api_key=SecretStr(settings.openai_api_key or "missing"),
    )


def supervisor(state: AgentState) -> dict[str, Any]:
    decision = (
        _chat_model()
        .with_structured_output(IntentDecision)
        .invoke([SystemMessage(SUPERVISOR_SYSTEM), *state["messages"]])
    )
    assert isinstance(decision, IntentDecision)
    return {"intent": decision.intent}


def route_by_intent(state: AgentState) -> str:
    intent = state.get("intent")
    if intent in ("deposit", "loan"):
        return intent
    return "general"


def general(state: AgentState) -> dict[str, Any]:
    reply = _chat_model().invoke([SystemMessage(GENERAL_AGENT_SYSTEM), *state["messages"]])
    return {"messages": [reply]}


def build_graph(
    checkpointer: BaseCheckpointSaver[Any] | None = None,
) -> CompiledStateGraph[AgentState, Any, Any, Any]:
    deposit_agent = create_agent(
        _chat_model(),
        tools=[compare_deposit_products, compare_saving_products],
        system_prompt=DEPOSIT_AGENT_SYSTEM,
    )
    loan_agent = create_agent(
        _chat_model(),
        tools=[compare_mortgage_loans, compare_rent_loans, compare_credit_loans],
        system_prompt=LOAN_AGENT_SYSTEM,
    )

    builder = StateGraph(AgentState)
    builder.add_node("supervisor", supervisor)
    builder.add_node("deposit", deposit_agent)
    builder.add_node("loan", loan_agent)
    builder.add_node("general", general)
    builder.add_edge(START, "supervisor")
    builder.add_conditional_edges("supervisor", route_by_intent, ["deposit", "loan", "general"])
    builder.add_edge("deposit", END)
    builder.add_edge("loan", END)
    builder.add_edge("general", END)
    return builder.compile(checkpointer=checkpointer)


@lru_cache
def get_agent() -> CompiledStateGraph[AgentState, Any, Any, Any]:
    """프로세스 전역 에이전트 — 멀티턴 상태는 메모리 체크포인터(thread_id)로 유지."""
    return build_graph(checkpointer=MemorySaver())
