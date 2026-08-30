"""LangGraph 멀티 에이전트 그래프 — supervisor(의도분류) + 상품군별 worker."""

# langgraph/langchain의 제네릭이 부분적으로 Unknown이라 파일 단위로만 완화한다
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false

import logging
from collections.abc import Sequence
from functools import lru_cache, partial
from typing import Any, Literal

from langchain.agents import create_agent
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.graph.state import CompiledStateGraph
from pydantic import BaseModel, SecretStr

from app.agents.prompts import (
    DEPOSIT_AGENT_SYSTEM,
    GENERAL_AGENT_SYSTEM,
    LOAN_AGENT_SYSTEM,
    OUT_OF_SCOPE_REPLY,
    SUPERVISOR_SYSTEM,
)
from app.agents.tools import (
    compare_credit_loans,
    compare_deposit_products,
    compare_mortgage_loans,
    compare_rent_loans,
    compare_saving_products,
    search_products_by_condition,
)
from app.core.config import get_settings
from app.db.checkpointer import make_checkpointer

Intent = Literal["deposit", "loan", "general", "out_of_scope"]

# LLM 입력으로 보내는 최근 메시지 수. 세션이 아무리 길어도 모든 모델 호출의
# 입력 크기를 여기서 상한한다 (메시지 개수 기준 — 대화가 사람/AI 텍스트뿐이라
# 토큰 추정기 없이도 충분히 안정적이다).
HISTORY_WINDOW = 12


class AgentState(MessagesState):
    intent: Intent


class IntentDecision(BaseModel):
    intent: Intent


def _ai_text(message: AIMessage) -> str:
    """AIMessage 본문 텍스트 — 블록형 콘텐츠여도 텍스트 블록만 이어 붙인다."""
    if isinstance(message.content, str):
        return message.content
    return "".join(
        block.get("text", "")
        for block in message.content
        if isinstance(block, dict) and block.get("type") == "text"
    )


def history_for_llm(messages: Sequence[AnyMessage]) -> list[AnyMessage]:
    """모델 입력용 대화 뷰 — 사람·AI 텍스트만 최근 HISTORY_WINDOW개 남긴다.

    도구 호출·결과 메시지는 걸러낸다. 워커의 도구 왕복이 이력에 실리면
    (1) 분류용 supervisor 입력에까지 상품표 전문이 매 턴 들어가고,
    (2) 다른 워커가 자기에게 바인딩되지 않은 도구를 이력에서 보고 흉내 내며,
    (3) tool_calls와 ToolMessage 짝이 잘리면 OpenAI가 400을 반환한다.
    본문과 tool_calls가 함께 있는 AIMessage는 본문만 남긴다.
    """
    kept: list[AnyMessage] = []
    for message in messages:
        if isinstance(message, HumanMessage):
            kept.append(message)
        elif isinstance(message, AIMessage):
            text = _ai_text(message)
            if text.strip():
                kept.append(AIMessage(text) if message.tool_calls else message)
    return kept[-HISTORY_WINDOW:]


def run_worker(agent: Any, state: AgentState) -> dict[str, Any]:
    """워커를 정리된 이력으로 호출하고 최종 답변만 부모 상태에 남긴다.

    중간 도구 호출·결과는 체크포인트에 올리지 않는다 — 후속 질문에 필요한
    정보는 최종 답변 텍스트(상품명·금리 목록)에 이미 들어 있다.
    """
    result = agent.invoke({"messages": history_for_llm(state["messages"])})
    return {"messages": [result["messages"][-1]]}


@lru_cache
def _chat_model() -> ChatOpenAI:
    """프로세스당 하나만 만든다 — 생성 시 sync·async httpx 클라이언트가 즉시 생기므로
    supervisor처럼 모든 요청이 지나는 경로에서 매번 만들면 커넥션 풀이 버려진다."""
    settings = get_settings()
    # 키가 없어도 그래프 구축은 가능해야 한다 (실 호출 시점에만 실패)
    return ChatOpenAI(
        model=settings.openai_model,
        api_key=SecretStr(settings.openai_api_key or "missing"),
    )


def supervisor(state: AgentState) -> dict[str, Any]:
    """마지막 사용자 메시지의 의도를 분류한다. 실패하면 general로 폴백한다.

    분류는 답변을 보조하는 단계라 여기서 죽으면 요청 전체가 502로 번진다 —
    route_by_intent가 미지 intent를 general로 보내는 것과 같은 철학이다.
    (API 장애처럼 general 호출도 함께 죽는 실패는 거기서 502가 되고,
    모델 거절·파싱 실패 같은 분류만의 실패는 대화가 이어진다.)
    """
    try:
        decision = (
            _chat_model()
            .with_structured_output(IntentDecision)
            .invoke([SystemMessage(SUPERVISOR_SYSTEM), *history_for_llm(state["messages"])])
        )
    except Exception:
        logging.exception("의도분류 실패 — general로 폴백")
        return {"intent": "general"}
    if not isinstance(decision, IntentDecision):
        logging.warning("의도분류 결과가 IntentDecision이 아님 (%r) — general로 폴백", decision)
        return {"intent": "general"}
    return {"intent": decision.intent}


def route_by_intent(state: AgentState) -> str:
    intent = state.get("intent")
    if intent in ("deposit", "loan", "out_of_scope"):
        return intent
    return "general"


def general(state: AgentState) -> dict[str, Any]:
    reply = _chat_model().invoke(
        [SystemMessage(GENERAL_AGENT_SYSTEM), *history_for_llm(state["messages"])]
    )
    return {"messages": [reply]}


def out_of_scope(state: AgentState) -> dict[str, Any]:
    """금융 범위 밖 질문은 LLM을 태우지 않고 고정 문구로 돌려보낸다.

    이유는 결정성이다 — 프롬프트로만 막으면 대화를 이어가며 설득당할 여지가
    남지만, 라우팅에서 끊은 거절은 말로 뒤집을 수 없다.
    분류용 supervisor 호출은 어차피 도므로 토큰이 공짜가 되지는 않고,
    답변 생성 호출 한 번(측정값 in 233 / out 427)을 아끼는 것이다.
    """
    return {"messages": [AIMessage(OUT_OF_SCOPE_REPLY)]}


def build_graph(
    checkpointer: BaseCheckpointSaver[Any] | None = None,
) -> CompiledStateGraph[AgentState, Any, Any, Any]:
    # 워커는 run_worker 래퍼로 호출한다. 자체 체크포인트는 남길 것이 없으므로
    # 부모 체크포인터 상속을 끈다(checkpointer=False).
    deposit_agent = create_agent(
        _chat_model(),
        tools=[compare_deposit_products, compare_saving_products, search_products_by_condition],
        system_prompt=DEPOSIT_AGENT_SYSTEM,
        checkpointer=False,
    )
    loan_agent = create_agent(
        _chat_model(),
        tools=[
            compare_mortgage_loans,
            compare_rent_loans,
            compare_credit_loans,
            search_products_by_condition,
        ],
        system_prompt=LOAN_AGENT_SYSTEM,
        checkpointer=False,
    )

    builder = StateGraph(AgentState)
    builder.add_node("supervisor", supervisor)
    builder.add_node("deposit", partial(run_worker, deposit_agent))
    builder.add_node("loan", partial(run_worker, loan_agent))
    builder.add_node("general", general)
    builder.add_node("out_of_scope", out_of_scope)
    builder.add_edge(START, "supervisor")
    builder.add_conditional_edges(
        "supervisor", route_by_intent, ["deposit", "loan", "general", "out_of_scope"]
    )
    builder.add_edge("deposit", END)
    builder.add_edge("loan", END)
    builder.add_edge("general", END)
    builder.add_edge("out_of_scope", END)
    return builder.compile(checkpointer=checkpointer)


@lru_cache
def get_agent() -> CompiledStateGraph[AgentState, Any, Any, Any]:
    """프로세스 전역 에이전트 — 멀티턴 상태(thread_id)는 DATABASE_URL 체크포인터로 유지."""
    return build_graph(checkpointer=make_checkpointer(get_settings().database_url))
