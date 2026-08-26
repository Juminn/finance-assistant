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
    # 인증 여부로 스레드를 분리해, 인증 상태에서 얻은 답변(신용대출 등)이
    # 같은 session_id의 비인증 요청 컨텍스트로 재주입되지 않게 한다
    thread_id = f"{user.id if user else 'anon'}:{session_id}"
    try:
        with authenticated_request(user is not None):
            result = get_agent().invoke(
                {"messages": [HumanMessage(body.message)]},
                config={"configurable": {"thread_id": thread_id}},
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
def history(session_id: str, db: DbDep, user: OptionalUserDep) -> HistoryResponse:
    rows = repo.history_for_session(db, session_id)

    # 로그인 사용자의 대화가 섞인 세션은 그 사용자 본인만 조회할 수 있다
    owner_ids = {m.user_id for m in rows if m.user_id is not None}
    if owner_ids and (user is None or owner_ids != {user.id}):
        raise HTTPException(status_code=403, detail="이 대화 이력을 볼 권한이 없습니다")

    messages = [HistoryMessage(role=m.role, content=m.content) for m in rows]
    return HistoryResponse(session_id=session_id, messages=messages)
