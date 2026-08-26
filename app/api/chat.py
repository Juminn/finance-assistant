# langgraph 그래프의 제네릭이 부분적으로 Unknown이라 invoke 지점만 완화한다
# pyright: reportUnknownMemberType=false

import logging
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from langchain_core.messages import HumanMessage
from pydantic import BaseModel

from app.agents.graph import get_agent
from app.api.deps import DbDep, OptionalUserDep
from app.core.auth_context import authenticated_request
from app.core.pii import mask_pii
from app.db import repo

router = APIRouter(tags=["chat"])


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None


class ChatResponse(BaseModel):
    session_id: str
    reply: str


class HistoryMessage(BaseModel):
    role: str
    content: str


class HistoryResponse(BaseModel):
    session_id: str
    messages: list[HistoryMessage]


@router.post("/chat")
def chat(body: ChatRequest, db: DbDep, user: OptionalUserDep) -> ChatResponse:
    session_id = body.session_id or uuid4().hex
    try:
        with authenticated_request(user is not None):
            result = get_agent().invoke(
                {"messages": [HumanMessage(body.message)]},
                config={"configurable": {"thread_id": session_id}},
            )
    except Exception:
        logging.exception("에이전트 호출 실패 (session_id=%s)", session_id)
        raise HTTPException(
            status_code=502, detail="답변 생성 중 오류가 발생했어요. 잠시 후 다시 시도해주세요."
        ) from None
    reply = mask_pii(str(result["messages"][-1].content))

    user_id = user.id if user else None
    repo.log_message(db, session_id, "user", body.message, user_id)
    repo.log_message(db, session_id, "assistant", reply, user_id)
    return ChatResponse(session_id=session_id, reply=reply)


@router.get("/history/{session_id}")
def history(session_id: str, db: DbDep) -> HistoryResponse:
    messages = [
        HistoryMessage(role=m.role, content=m.content)
        for m in repo.history_for_session(db, session_id)
    ]
    return HistoryResponse(session_id=session_id, messages=messages)
